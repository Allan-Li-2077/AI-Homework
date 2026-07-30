"""
CLI 版 Agent — 四层记忆联动演示 + 技能自动执行（通用版）
"""

import os
import sys
import logging
from pathlib import Path
import re

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent.parent))
# 确保工作目录为项目根，使 skills/ 等相对路径始终可用
os.chdir(Path(__file__).parent.parent)

from src.session_db import SessionDB
from src.memory_loader import MemoryLoader
from src.vector_store import VectorStore
from src.fts_store import FTSStore
from src.retrieval import HybridRetriever
from src.memory_flush import MemoryFlusher
from src.llm_config import get_chat_client, current_model_info
from src.skill_loader import SkillLoader
from src.task_planner import (
    build_script_prompt,
    ScriptExecutor,
    format_script_summary,
)

logging.basicConfig(level=logging.WARNING)
AUTO_FLUSH_THRESHOLD = 20

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
DIM = "\033[2m"

# ---------- 辅助函数 ----------
def print_layer_info(layers, semantic_results=None):
    print(f"\n{CYAN}{'─'*60}{RESET}")
    print(f"{CYAN}  四层记忆加载情况{RESET}")
    print(f"{CYAN}{'─'*60}{RESET}")
    layer_icons = {"soul": "🧠", "daily_log": "🫧", "user_profile": "👤", "agents_manual": "📋", "long_term_memory": "💾"}
    layer_names = {
        "soul": "Layer 3a  SOUL.md（人格定义）",
        "daily_log": "Layer 2   每日日志（今天 + 昨天）",
        "user_profile": "Layer 3b  USER.md（用户画像）",
        "agents_manual": "Layer 3c  AGENTS.md（操作规范）",
        "long_term_memory": "Layer 3d  MEMORY.md（长期记忆）",
    }
    for layer in layers:
        name = layer_names.get(layer.name, layer.name)
        chars = layer.char_count
        print(f"  {layer_icons.get(layer.name, '·')} {name}  {DIM}[{chars} 字符]{RESET}")

    if semantic_results:
        print(f"  🔍 Layer 4   混合检索（向量 0.7 + BM25 0.3）  {DIM}[{len(semantic_results)} 条命中]{RESET}")
        for r in semantic_results:
            score_pct = int(r["score"] * 100)
            cat = r.get("category", "?")
            title = r.get("title", r.get("content", "")[:30])
            src = r.get("source", "?")
            print(f"      {DIM}[{cat}] {title}  相似度 {score_pct}%  来源:{src}{RESET}")
    else:
        print(f"  🔍 Layer 4   混合检索（向量 0.7 + BM25 0.3）  {DIM}[暂无命中]{RESET}")
    print(f"{CYAN}{'─'*60}{RESET}\n")


def do_flush(flusher, db, session_id):
    messages = db.get_session_messages(session_id)
    user_messages = [m for m in messages if m["role"] in ("user", "assistant")]
    if not user_messages:
        print(f"{YELLOW}会话为空，跳过 Flush。{RESET}")
        return

    print(f"\n{MAGENTA}{'═'*60}{RESET}")
    print(f"{MAGENTA}  Memory Flush 开始...{RESET}")
    print(f"{MAGENTA}{'═'*60}{RESET}")
    print(f"  分析 {len(user_messages)} 条消息...")

    result = flusher.flush(user_messages, session_id)

    if result.error:
        print(f"{YELLOW}  [错误] {result.error}{RESET}")
        return

    print(f"\n  {GREEN}Pass 1 — 用户信息更新 ({len(result.user_updates)} 项){RESET}")
    for u in result.user_updates:
        print(f"    ✓ {u}")
    if not result.user_updates:
        print(f"    {DIM}（无新信息）{RESET}")

    print(f"\n  {GREEN}Pass 2 — 新增长期记忆 ({len(result.new_memory_entries)} 条){RESET}")
    for e in result.new_memory_entries:
        cat = e.get("category", "?")
        title = e.get("title", "")
        print(f"    [{cat}] {title}")
    if not result.new_memory_entries:
        print(f"    {DIM}（无新记忆）{RESET}")

    print(f"\n  {GREEN}Pass 3 — 向量化写入 FAISS：{result.vectorized_count} 条{RESET}")

    if result.compacted:
        print(f"\n  {YELLOW}Compaction：{result.compaction_before} → {result.compaction_after} 条{RESET}")

    db.mark_flushed(session_id)
    print(f"\n{MAGENTA}{'═'*60}{RESET}")
    print(f"{MAGENTA}  Flush 完成！长期记忆已更新。{RESET}")
    print(f"{MAGENTA}{'═'*60}{RESET}\n")


def show_memory(loader):
    user_md = loader.get_user_md_path().read_text(encoding="utf-8")
    memory_md = loader.get_memory_md_path().read_text(encoding="utf-8")
    entry_count = loader.get_memory_entry_count()
    print(f"\n{CYAN}=== USER.md ==={RESET}")
    print(user_md[:1500])
    print(f"\n{CYAN}=== MEMORY.md ({entry_count} 条记忆条目) ==={RESET}")
    print(memory_md[:2000])
    print()


# ---------- 主程序 ----------
def main():
    model_info = current_model_info()
    print(f"\n{BOLD}Agent 记忆系统 — CLI 演示 (技能自动执行 + 任务规划){RESET}")
    print(f"当前模型：{CYAN}{model_info['display']}{RESET}  "
          f"{DIM}（切换：LLM_PROVIDER=deepseek 或 qwen）{RESET}")
    print("输入 /flush, /memory, /layers, /new, /exit 查看各功能")
    print(f"{DIM}技能请求 → LLM 生成 Python 脚本 → 保存到临时文件 → 执行 → 自动清理{RESET}\n")

    try:
        get_chat_client()
    except EnvironmentError as e:
        print(f"{YELLOW}{e}{RESET}")
        sys.exit(1)

    db = SessionDB()
    loader = MemoryLoader()
    vs = VectorStore()
    fts = FTSStore()
    retriever = HybridRetriever(vs, fts)
    flusher = MemoryFlusher()
    skill_loader = SkillLoader()
    all_skills = skill_loader.load_all_skills()
    skill_loader.print_skills_info(all_skills)

    skills_brief = "\n".join([f"- {s.name}: {s.brief}" for s in all_skills])

    session_id = db.new_session()
    prompt_result = loader.build_system_prompt(recent_memory_limit=10)
    print_layer_info(prompt_result.layers)

    messages = []
    auto_approve = os.environ.get("AUTO_APPROVE_EXEC", "").lower() in ("1", "true", "yes")

    while True:
        try:
            user_input = input(f"{BOLD}你：{RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            user_input = "/exit"

        if not user_input:
            continue

        # ── 命令处理 ──────────────────────────────────────────────────
        if user_input == "/exit":
            do_flush(flusher, db, session_id)
            db.close_session(session_id, title=messages[0]["content"][:30] if messages else "空会话")
            print("再见！")
            break

        if user_input == "/flush":
            do_flush(flusher, db, session_id)
            prompt_result = loader.build_system_prompt(recent_memory_limit=10)
            continue

        if user_input == "/memory":
            show_memory(loader)
            continue

        if user_input == "/layers":
            query = messages[-1]["content"] if messages else ""
            semantic = retriever.search(query, top_k=3) if query else []
            prompt_result = loader.build_system_prompt(recent_memory_limit=10)
            print_layer_info(prompt_result.layers, semantic)
            continue

        if user_input == "/new":
            db.close_session(session_id, title=messages[0]["content"][:30] if messages else "空会话")
            session_id = db.new_session()
            messages = []
            prompt_result = loader.build_system_prompt(recent_memory_limit=10)
            print(f"{GREEN}新会话已开始，记忆已重新加载。{RESET}")
            print_layer_info(prompt_result.layers)
            continue

        # ── Layer 4：混合检索 ──────────────────────────────────────
        semantic_results = retriever.search(user_input, top_k=3)
        if semantic_results:
            print(f"  {DIM}[混合检索] 找到 {len(semantic_results)} 条相关记忆{RESET}")

        semantic_context = ""
        if semantic_results:
            snippets = [f"- [{r['category']}] {r['content'][:100]}" for r in semantic_results]
            semantic_context = "相关历史记忆：\n" + "\n".join(snippets)

        # 构建基础 system prompt（不含技能相关）
        base_system_prompt = prompt_result.system_prompt
        if semantic_context:
            base_system_prompt += f"\n\n## 语义检索到的相关记忆\n{semantic_context}"

        # 构建技能相关指令（第一次请求使用）
        skills_instruction = ""
        if skills_brief:
            skills_instruction = (
                f"\n\n## 可用技能（仅名称和简介）\n{skills_brief}\n"
                "如果用户请求需要调用某个技能来完成，你应当：\n"
                "1. 先判断是否适用。\n"
                "2. 在回答中输出 `[SKILL: 技能名称]`（单独一行），表明你需要该技能的详细说明。\n"
                "3. 不要直接输出命令，稍后系统会加载详细说明并让你规划执行。\n"
                "如果有多个技能可选，可以先询问用户。\n"
            )

        # 第一次请求的 system prompt
        system_prompt_first = base_system_prompt + skills_instruction

        api_messages = [{"role": "system", "content": system_prompt_first}] + messages
        api_messages.append({"role": "user", "content": user_input})

        # === 第一阶段：获取 LLM 响应，检测技能标记 ===
        client, model = get_chat_client()
        first_resp = client.chat.completions.create(
            model=model,
            messages=api_messages,
            temperature=0.7,
            stream=False,
        )
        first_content = first_resp.choices[0].message.content
        print(f"{GREEN}[DEBUG] LLM输出: {first_content}")

        skill_pattern = r'\[SKILL:\s*(\S+)\]'
        match = re.search(skill_pattern, first_content)

        if match:
            skill_name = match.group(1)
            print(f"{GREEN}[调试] 检测到技能调用请求：{skill_name}{RESET}")
            detail = skill_loader.get_skill_detail(skill_name)
            if detail:
                print(f"{GREEN}[调试] 成功加载技能 `{skill_name}` 的详细说明（{len(detail)} 字符）{RESET}")
                skill_folder = skill_loader.get_skill_folder(skill_name)

                script_instruction = build_script_prompt(skill_name, detail, user_input, skill_folder)
                script_system = base_system_prompt + "\n\n" + script_instruction

                script_messages = [{"role": "system", "content": script_system}] + messages
                script_messages.append({"role": "user", "content": user_input})

                print(f"{GREEN}[DEBUG] 给大模型的提示词 (脚本模式): {script_messages}")

                print(f"{GREEN}[调试] 正在生成 Python 脚本...{RESET}")
                script_resp = client.chat.completions.create(
                    model=model,
                    messages=script_messages,
                    temperature=0.3,
                    stream=False,
                )
                script_text = script_resp.choices[0].message.content

                script_executor = ScriptExecutor(Path.cwd(), auto_approve=auto_approve)
                exec_result = script_executor.execute(
                    script_text,
                    goal=user_input[:40],
                    confirm=True,
                )

                response_text = format_script_summary(exec_result)
                print(f"{GREEN}Muse：{RESET}")
                print(response_text)
                print()
            else:
                print(f"{YELLOW}[调试] 未找到技能 `{skill_name}` 的详细说明，使用原回答{RESET}")
                print(f"{YELLOW}未找到技能 '{skill_name}'，直接回答：{RESET}")
                print(first_content)
                response_text = first_content
        else:
            print(f"{GREEN}Muse：{RESET}", end="")
            for ch in first_content:
                print(ch, end="", flush=True)
            print()
            response_text = first_content

        # 记录到数据库 + 本地列表
        db.add_message(session_id, "user", user_input)
        db.add_message(session_id, "assistant", response_text)
        messages.append({"role": "user", "content": user_input})
        messages.append({"role": "assistant", "content": response_text})

        if db.get_message_count(session_id) >= AUTO_FLUSH_THRESHOLD:
            print(f"\n{YELLOW}[自动触发 Flush：消息数达到 {AUTO_FLUSH_THRESHOLD}]{RESET}")
            do_flush(flusher, db, session_id)
            prompt_result = loader.build_system_prompt(recent_memory_limit=10)


if __name__ == "__main__":
    main()