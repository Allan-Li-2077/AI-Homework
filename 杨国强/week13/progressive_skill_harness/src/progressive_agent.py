"""
Progressive Agent — 核心循环：六层渐进式加载

教学重点：
  这是整个 harness 的"调度主循环"，每轮对话按以下顺序执行：

    Layer 3 (全量加载)
      ├─ SOUL.md     — 人格定义
      ├─ USER.md     — 用户画像
      └─ AGENTS.md   — 操作规范

    Layer S0 (轻量索引)
      └─ SkillRegistry.build() — 只读 frontmatter，不读正文

    Layer S1 (按需)
      ├─ Keyword 粗筛 → 候选 skill 列表
      └─ LLM 精筛   → 决策（direct / skill_call / chain）

    Layer S2 (按需)
      └─ 决策命中的 skill 读 SKILL.md 正文 → SkillContract

    Layer 4 (按需检索)
      └─ HybridRetriever.search() — FAISS + FTS5

    Layer S3 (按需)
      └─ SkillExecutor.run() — 执行 skill

    Layer S4 (后置写入)
      └─ SkillRecorder.record_call() — 写入 USER.md / MEMORY.md / FAISS / FTS5

    最后：组装 system prompt → LLM 流式生成回答

  关键点："渐进"体现在：
    - 启动时 O(N) × frontmatter，**N 个 skill 总共 ~5KB**
    - 实际正文读取 O(k)，**只有被选中的 k 个**
    - LLM system prompt 中只注入被选中的 skill 正文

使用方式：
  agent = ProgressiveAgent()
  for event in agent.handle(user_input):
      # event = {"type": "...", ...}  可直接推给前端 SSE
      print(event)
"""

import os
import sys
import logging
from pathlib import Path
from typing import Iterator
from dataclasses import dataclass, field

# Windows OpenMP 冲突
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.session_db import SessionDB
from src.memory_loader import MemoryLoader
from src.vector_store import VectorStore
from src.fts_store import FTSStore
from src.retrieval import HybridRetriever
from src.llm_config import get_chat_client

from src.skill_registry import get_registry, reload_registry, SkillRegistry
from src.skill_selector import SkillSelector, SkillDecision
from src.skill_loader import SkillLoader, SkillContract
from src.skill_executor import SkillExecutor, SkillResult
from src.skill_recorder import SkillRecorder

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ANSI 颜色
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
DIM = "\033[2m"


@dataclass
class AgentEvent:
    """一个结构化事件，便于序列化给前端"""
    type: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, **self.data}


class ProgressiveAgent:
    def __init__(self):
        # ── 记忆系统（复用原项目） ──
        self.db = SessionDB()
        self.loader = MemoryLoader()
        self.vs = VectorStore()
        self.fts = FTSStore()
        self.retriever = HybridRetriever(self.vs, self.fts)

        # ── Skill 系统（本次新增） ──
        self.registry: SkillRegistry = get_registry()
        self.selector = SkillSelector(self.registry)
        self.loader_skill = SkillLoader(self.registry)
        self.executor = SkillExecutor()
        self.recorder = SkillRecorder()

        self.session_id: int = self.db.new_session()
        self.messages: list[dict] = []    # 当前会话上下文
        self.recent_skills: list[str] = []  # 最近用过的 skill（给 selector 当 hint）

    # ── 主入口 ────────────────────────────────────────────────────────────────

    def handle(self, user_input: str) -> Iterator[AgentEvent]:
        """处理一轮用户输入，返回事件流"""
        # ── Layer 3：长期记忆加载（人格 + 用户 + 规范） ──────────────────────
        prompt_result = self.loader.build_system_prompt(recent_memory_limit=10)
        yield AgentEvent("layer3_load", {
            "layers": [
                {"name": l.name, "source": l.source_file, "chars": l.char_count}
                for l in prompt_result.layers
            ],
            "total_chars": prompt_result.total_chars,
        })

        # ── Layer S0：Skill 注册表（启动时已建好，事件回显） ────────────────
        registry_summary = self.registry.summary()
        yield AgentEvent("layer_s0_registry", registry_summary)

        # ── Layer S1：Skill 决策 ──────────────────────────────────────────────
        decision: SkillDecision = self.selector.decide(
            user_input, history=self.messages, recent_skills=self.recent_skills
        )
        yield AgentEvent("layer_s1_decision", {
            "action": decision.action,
            "confidence": decision.confidence,
            "skills": decision.skills,
            "direct_reason": decision.direct_reason,
            "candidates": decision.candidates,
            "skipped_candidates": decision.skipped_candidates,
        })

        skill_results: list[SkillResult] = []

        # ── Layer S2 + S3：按需加载 + 执行 ──────────────────────────────────
        if decision.action in ("skill_call", "chain") and decision.skills:
            for call in decision.skills:
                skill_name = call.get("name")
                params = call.get("params", {})
                contract: SkillContract | None = self.loader_skill.load(
                    skill_name, params=params
                )
                if not contract:
                    yield AgentEvent("layer_s2_load_failed", {
                        "skill_name": skill_name,
                        "reason": "SKILL.md 加载失败",
                    })
                    continue

                yield AgentEvent("layer_s2_load", {
                    "skill_name": skill_name,
                    "execution": contract.meta.execution,
                    "body_chars": len(contract.body_md),
                    "load_time_ms": contract.load_time_ms,
                    "cache_hit": contract.cache_hit,
                    "content_hash": contract.content_hash,
                    "params": contract.params_resolved,
                    "params_missing": contract.params_missing,
                })

                # 注入广播：把 executor 的事件转发出来
                def _broadcast(t: str, d: dict, _name=skill_name):
                    return AgentEvent(f"layer_s3_{t}", {**d, "skill_name": _name})

                # 简易代理：SkillExecutor.broadcast 接受 (event_type, data)
                event_buffer: list[AgentEvent] = []
                def buffered_broadcast(t: str, d: dict):
                    event_buffer.append(_broadcast(t, d))

                self.executor.set_broadcast(buffered_broadcast)
                result = self.executor.run(contract, context={
                    "user_query": user_input,
                    "memory_snippets": self._recent_memory_snippets(user_input),
                    "user_profile": self._read_user_profile(),
                    "recent_skill_results": [
                        {"skill_name": r.skill_name, "text": r.text}
                        for r in skill_results
                    ],
                }, user_query=user_input)

                for ev in event_buffer:
                    yield ev
                skill_results.append(result)
                self.recent_skills.append(skill_name)

                # 写入记忆
                try:
                    self.recorder.record_call(
                        skill_name=skill_name,
                        params=params,
                        result_text=result.text or "",
                        user_query=user_input,
                        success=result.success,
                        duration_ms=result.duration_ms,
                    )
                except Exception as e:
                    logger.warning(f"记录 skill 调用失败：{e}")

        # ── Layer 4：混合检索（向量 + BM25） ──────────────────────────────────
        semantic_results = self.retriever.search(user_input, top_k=3)
        yield AgentEvent("layer4_semantic_search", {
            "query": user_input,
            "results": [
                {
                    "category": r.get("category", ""),
                    "title": r.get("title", ""),
                    "content": (r.get("content", "") or "")[:120],
                    "score": round(r.get("score", 0.0), 3),
                    "source": r.get("source", ""),
                }
                for r in semantic_results
            ],
        })

        # ── 组装 Context Window ──────────────────────────────────────────────
        skill_snippets = []
        for r in skill_results:
            if r.success and r.text:
                preview = r.text[:400] + ("…" if len(r.text) > 400 else "")
                skill_snippets.append(f"### Skill [{r.skill_name}]\n{preview}")

        semantic_snippets = [
            f"- [{r.get('category','')}] {r.get('title','')}: {(r.get('content','') or '')[:100]}"
            for r in semantic_results
        ]

        system_prompt = prompt_result.system_prompt
        if skill_snippets:
            system_prompt += "\n\n## Skill 调用结果\n" + "\n\n".join(skill_snippets)
        if semantic_snippets:
            system_prompt += "\n\n## 相关历史记忆\n" + "\n".join(semantic_snippets)

        yield AgentEvent("context_assembly", {
            "system_chars": len(system_prompt),
            "history_turns": len(self.messages),
            "layers_used": (
                ["layer3:" + l.name for l in prompt_result.layers]
                + ["layer_s0:registry"]
                + (["layer_s1:decision"] if decision.action != "direct_answer" else [])
                + [f"layer_s3:{r.skill_name}" for r in skill_results if r.success]
                + (["layer4:semantic"] if semantic_results else [])
            ),
        })

        # ── LLM 流式生成最终回复 ──────────────────────────────────────────────
        api_messages = (
            [{"role": "system", "content": system_prompt}]
            + self.messages
            + [{"role": "user", "content": user_input}]
        )

        yield AgentEvent("llm_start", {"model": "chat"})

        full_response = ""
        try:
            client, model = get_chat_client()
            stream = client.chat.completions.create(
                model=model, messages=api_messages, temperature=0.7, stream=True
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    full_response += delta
                    yield AgentEvent("token", {"text": delta})
        except Exception as e:
            yield AgentEvent("error", {"message": f"LLM 调用失败：{e}"})
            full_response = f"（系统错误：{e}）"

        # ── 写入数据库 + 本地消息列表 ─────────────────────────────────────────
        self.db.add_message(self.session_id, "user", user_input)
        self.db.add_message(self.session_id, "assistant", full_response)
        self.messages.append({"role": "user", "content": user_input})
        self.messages.append({"role": "assistant", "content": full_response})

        yield AgentEvent("done", {
            "response": full_response,
            "session_id": self.session_id,
            "message_count": self.db.get_message_count(self.session_id),
            "skills_used": [r.skill_name for r in skill_results if r.success],
        })

    # ── 辅助 ──────────────────────────────────────────────────────────────────

    def _recent_memory_snippets(self, query: str) -> list[str]:
        results = self.retriever.search(query, top_k=2)
        return [f"[{r.get('category','')}] {r.get('content','')[:150]}" for r in results]

    def _read_user_profile(self) -> str:
        p = self.loader.get_user_md_path()
        if p.exists():
            return p.read_text(encoding="utf-8")[:1500]
        return ""

    def new_session(self) -> int:
        if self.session_id:
            self.db.close_session(self.session_id)
        self.session_id = self.db.new_session()
        self.messages = []
        self.recent_skills = []
        return self.session_id


# ── CLI 入口 ───────────────────────────────────────────────────────────────────

def main():
    print(f"\n{BOLD}Progressive Skill Harness — CLI 演示{RESET}")
    print(f"{CYAN}已索引 {len(get_registry())} 个 skill（仅元数据，启动成本 < 5KB）{RESET}")
    print("命令：/skills（列表）、/memory（查看记忆）、/new（新会话）、/exit\n")

    try:
        get_chat_client()
    except EnvironmentError as e:
        print(f"{YELLOW}{e}{RESET}")
        sys.exit(1)

    agent = ProgressiveAgent()

    while True:
        try:
            user_input = input(f"{BOLD}你：{RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            user_input = "/exit"
        if not user_input:
            continue

        if user_input == "/exit":
            print("再见！")
            break
        if user_input == "/skills":
            for m in agent.registry.items():
                print(f"  {GREEN}•{RESET} {BOLD}{m.name}{RESET} ({m.execution}, {m.body_chars} 字符正文)")
                print(f"    {DIM}{m.short_desc(80)}{RESET}")
                if m.keywords:
                    print(f"    {DIM}keywords: {', '.join(m.keywords)}{RESET}")
            print()
            continue
        if user_input == "/memory":
            print(f"\n{CYAN}=== MEMORY.md ==={RESET}")
            print(agent.loader.get_memory_md_path().read_text(encoding="utf-8")[:2000])
            print()
            continue
        if user_input == "/new":
            agent.new_session()
            print(f"{GREEN}新会话 #{agent.session_id}{RESET}\n")
            continue

        # ── 处理一轮 ──
        print(f"{CYAN}{'─'*60}{RESET}")
        print(f"{MAGENTA}  渐进式加载流程{RESET}")
        print(f"{CYAN}{'─'*60}{RESET}")
        print(f"{GREEN}Assistant：{RESET}", end="", flush=True)

        for event in agent.handle(user_input):
            if event.type == "layer_s0_registry":
                print(f"\n  {DIM}[S0] 启动成本：{event.data.get('frontmatter_total_chars',0)} 字符 frontmatter，"
                      f"{event.data.get('body_total_chars',0)} 字符正文待加载{RESET}")
            elif event.type == "layer_s1_decision":
                action = event.data.get("action")
                conf = event.data.get("confidence", 0)
                if action == "direct_answer":
                    print(f"\n  {DIM}[S1] 决策：直接回答（{event.data.get('direct_reason','')[:60]}，置信度 {conf:.0%}）{RESET}")
                else:
                    skills = event.data.get("skills", [])
                    print(f"\n  {DIM}[S1] 决策：{action.upper()} 候选 → 命中 {len(skills)} 个 skill{RESET}")
                    for s in skills:
                        print(f"      • {s['name']}: {s.get('reason','')[:60]}")
            elif event.type == "layer_s2_load":
                ch = event.data.get("cache_hit", False)
                t = event.data.get("load_time_ms", 0)
                print(f"  {DIM}[S2] 加载 '{event.data['skill_name']}'："
                      f"{'命中缓存' if ch else f'{event.data.get('body_chars',0)} 字符, {t:.1f}ms'}{RESET}")
            elif event.type == "layer_s3_skill_execution_start":
                print(f"  {YELLOW}[S3] 执行 '{event.data['skill_name']}' ({event.data.get('execution')}){RESET}")
            elif event.type == "layer_s3_skill_execution_done":
                status = "✓" if event.data.get("success") else "✗"
                print(f"  {DIM}[S3] {status} '{event.data['skill_name']}' 完成，{event.data.get('duration_ms',0):.0f}ms"
                      f"  约 {event.data.get('tokens_streamed',0)} token{RESET}")
            elif event.type == "layer4_semantic_search":
                n = len(event.data.get("results", []))
                if n > 0:
                    print(f"  {DIM}[L4] 混合检索命中 {n} 条记忆{RESET}")
            elif event.type == "token":
                print(event.data.get("text", ""), end="", flush=True)
            elif event.type == "done":
                print(f"\n  {DIM}[结束] 共 {event.data.get('message_count',0)} 条消息，"
                      f"本次使用 skill: {', '.join(event.data.get('skills_used',[])) or '（无）'}{RESET}")
        print("\n")


if __name__ == "__main__":
    main()