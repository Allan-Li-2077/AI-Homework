"""
Skill 选择器 — Layer S1：决定"本次对话是否需要 skill + 用哪个"

教学重点：
  1. **两层筛选**：先用 keyword 粗筛（零 LLM 成本），再用 LLM 精筛（只看 ~500 字符的 description）
  2. 与 Cursor/Claude Code 的工具选择一致：给 LLM 一份"工具目录"，让它输出 JSON 决策
  3. 决策分三类：
     - skill_call: 需要调用 skill，给出 skill 名 + 参数
     - direct_answer: 不需要 skill，直接 LLM 回答
     - chain: 多个 skill 串行/并行（v1 仅支持串行）

使用方式：
  from src.skill_selector import SkillSelector
  selector = SkillSelector(registry)
  decision = selector.decide(user_query, conversation_history)
  # decision.action: "skill_call" | "direct_answer" | "chain"
  # decision.skills: [{name, params, reason}, ...]
  # decision.confidence: 0.0 ~ 1.0
"""

import json
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

from src.skill_registry import SkillRegistry, SkillMeta
from src.llm_config import get_chat_client

logger = logging.getLogger(__name__)


@dataclass
class SkillDecision:
    """一次决策的完整结果"""
    action: str                                    # skill_call / direct_answer / chain
    skills: list[dict] = field(default_factory=list)   # [{name, params, reason}]
    direct_reason: str = ""                        # action=direct_answer 时的理由
    confidence: float = 0.0                        # LLM 自评的可信度
    raw_response: str = ""                         # LLM 原始输出，便于调试
    candidates: list[str] = field(default_factory=list)  # 候选 skill 名（用于前端展示）
    skipped_candidates: list[str] = field(default_factory=list)  # 粗筛后被淘汰的


_SELECT_PROMPT = """你是一个 AI Agent 的"技能调度器"。你的任务：根据用户的请求，决定是否需要调用一个 Skill。

# 可用的 Skills（仅展示元数据，未加载正文）
{catalog}

# 用户当前请求
{query}

# 最近 3 轮对话上下文（用于消歧）
{context}

# 你的决策
请只返回如下 JSON（不要有其他文字）：
{{
  "action": "skill_call" | "direct_answer" | "chain",
  "confidence": 0.0 ~ 1.0,
  "skills": [
    {{ "name": "<skill 名>", "params": {{"<参数名>": "<参数值>"}}, "reason": "<一句话理由>" }}
  ],
  "direct_reason": "<仅 direct_answer 时填写：一句话说明为什么不需要 skill>"
}}

判断规则：
1. 如果用户请求能**直接由通用 LLM 回答**（闲聊、解释概念、写一般性文字）→ direct_answer
2. 如果用户请求**匹配某个 skill 的 keywords / triggers**（如"搜索最新新闻"、"翻译"、"代码审查"）→ skill_call
3. 如果需要**多个 skill 配合**（如"翻译这段代码并解释"）→ chain（按顺序调用）
4. 优先 keywords/triggers 命中的 skill；只有都不命中时才考虑 description 的语义匹配
5. 严格只返回 catalog 里出现的 skill 名，不要编造
6. 如果完全不确定，confidence 给低值（如 0.3），action=direct_answer
"""


class SkillSelector:
    def __init__(self, registry: SkillRegistry, max_candidates: int = 6):
        self.registry = registry
        self.max_candidates = max_candidates

    # ── 粗筛 ──────────────────────────────────────────────────────────────────

    def _coarse_filter(self, query: str) -> tuple[list[SkillMeta], list[str]]:
        """第一层：keyword/trigger 粗筛，零 LLM 成本"""
        hits = self.registry.search_by_keyword(query)
        kept = hits[: self.max_candidates]
        skipped = [m.name for m in hits[self.max_candidates :]] + [
            n for n in self.registry.names() if n not in {m.name for m in hits}
        ]
        return kept, skipped

    # ── 精筛 ──────────────────────────────────────────────────────────────────

    def decide(
        self,
        query: str,
        history: Optional[list[dict]] = None,
        recent_skills: Optional[list[str]] = None,
    ) -> SkillDecision:
        """第二层：LLM 基于粗筛结果做精确决策"""
        kept, skipped = self._coarse_filter(query)
        if not kept:
            # 没有任何 skill 命中 → 直接回答
            return SkillDecision(
                action="direct_answer",
                direct_reason="无可用 skill 与该请求匹配",
                confidence=0.5,
                candidates=[],
                skipped_candidates=skipped,
            )

        catalog = self._format_catalog(kept, recent_skills or [])
        context = self._format_context(history or [])
        prompt = _SELECT_PROMPT.format(catalog=catalog, query=query, context=context)

        try:
            client, model = get_chat_client()
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            raw = resp.choices[0].message.content.strip()
            data = self._parse_json_safe(raw)
        except Exception as e:
            logger.error(f"Skill 选择 LLM 调用失败：{e}")
            return SkillDecision(
                action="direct_answer",
                direct_reason=f"LLM 调用失败：{e}",
                confidence=0.0,
                candidates=[m.name for m in kept],
                skipped_candidates=skipped,
                raw_response=str(e),
            )

        if not data:
            return SkillDecision(
                action="direct_answer",
                direct_reason="LLM 输出无法解析，安全降级为直接回答",
                confidence=0.2,
                candidates=[m.name for m in kept],
                skipped_candidates=skipped,
                raw_response=raw,
            )

        return SkillDecision(
            action=data.get("action", "direct_answer"),
            skills=data.get("skills", []),
            direct_reason=data.get("direct_reason", ""),
            confidence=float(data.get("confidence", 0.5)),
            raw_response=raw,
            candidates=[m.name for m in kept],
            skipped_candidates=skipped,
        )

    # ── 辅助 ──────────────────────────────────────────────────────────────────

    def _format_catalog(self, metas: list[SkillMeta], recent_skills: list[str]) -> str:
        """把元数据格式化成 LLM 友好的'目录'"""
        lines: list[str] = []
        for i, m in enumerate(metas, 1):
            param_lines = []
            for p in m.parameters:
                req = "必填" if p.required else "可选"
                desc = f" — {p.description}" if p.description else ""
                param_lines.append(f"        - `{p.name}` ({p.type}, {req}){desc}")
            params_block = "\n".join(param_lines) if param_lines else "        （无参数）"

            recent_tag = "  ⭐ 最近使用过" if m.name in recent_skills else ""

            lines.append(
                f"  [{i}] **{m.name}** (v{m.version}){recent_tag}\n"
                f"      类型：{m.execution}\n"
                f"      描述：{m.description}\n"
                f"      关键词：{', '.join(m.keywords) if m.keywords else '（无）'}\n"
                f"      triggers：{', '.join(m.triggers) if m.triggers else '（无）'}\n"
                f"      参数：\n{params_block}"
            )
        return "\n\n".join(lines) if lines else "（无可用 skill）"

    def _format_context(self, history: list[dict]) -> str:
        """最近 N 轮对话摘要"""
        if not history:
            return "（无）"
        tail = history[-6:]  # 最近 3 轮 = 6 条消息
        return "\n".join(
            f"{'用户' if m['role'] == 'user' else '助手'}：{m['content'][:150]}"
            for m in tail
        )

    @staticmethod
    def _parse_json_safe(text: str) -> Optional[dict]:
        """容错解析 LLM 输出"""
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
        text = re.sub(r"\n?```$", "", text.strip())
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return None