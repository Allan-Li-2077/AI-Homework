"""Skill 路由器（Stage 1）。

把所有 skill 的 ``index_line`` 拼成索引发给 LLM，用 ``response_format=json_object``
要求返回 ``{"skill", "confidence", "reason"}``，按 confidence 阈值决定是否命中。
"""
from __future__ import annotations

import json
import logging
import re

from .llm import LLM
from .loader import SkillMeta, SkillRegistry

log = logging.getLogger("harness.selector")

__all__ = ["Selector"]

SELECTOR_SYSTEM = """你是一个 skill 路由器。根据用户输入，从下面的 skill 索引中选出最匹配的一个，或判断没有匹配。

【skill 索引】
{index}

【选择规则】
1. 优先匹配 skill 描述中的"触发场景 / Use when"措辞。
2. 标记为 [manual] 的 skill，必须用户话语与触发场景明确吻合才可选；仅模糊提及不可选。
3. 若用户输入是闲聊、问答或不在任何 skill 范围内，skill 字段返回 null。
4. confidence 反映你对匹配的确信度（0.0-1.0），低于 0.6 视为不确定。

【输出格式】
必须输出 JSON（输出必须是合法 JSON），字段：
- skill: 字符串，选中的 skill name；无匹配时为 null
- confidence: 数字
- reason: 一句话理由

示例：
输入"给我做张 crazy 词的闪卡" → {{"skill":"flash-card","confidence":0.95,"reason":"用户明确要求生成单词闪卡"}}
输入"今天天气怎么样" → {{"skill":null,"confidence":0.0,"reason":"无匹配 skill"}}
"""


class Selector:
    """基于 LLM 的 skill 选择器。"""

    def __init__(self, llm: LLM, registry: SkillRegistry, threshold: float = 0.6):
        self.llm = llm
        self.registry = registry
        self.threshold = threshold

    def select(self, user_input: str, history: list[dict] | None = None) -> SkillMeta | None:
        """返回命中的 SkillMeta，未命中或低于阈值返回 None。"""
        skills = self.registry.all()
        if not skills:
            return None
        index = "\n".join(s.index_line() for s in skills)
        sys_prompt = SELECTOR_SYSTEM.format(index=index)
        user_msg = self._build_user_msg(user_input, history)
        try:
            resp = self.llm.chat(
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("selector LLM call failed: %s -> fallback to chat", e)
            return None

        raw = resp.choices[0].message.content or "{}"
        data = self._safe_parse(raw)
        name = data.get("skill")
        conf = float(data.get("confidence", 0.0) or 0.0)
        reason = data.get("reason", "")
        log.info("[stage1] selected=%s conf=%.2f reason=%s", name, conf, reason)

        if not name or str(name).lower() in ("null", "none"):
            return None
        meta = self.registry.get(str(name))
        if meta is None:
            log.warning("LLM picked unknown skill %s", name)
            return None
        if conf < self.threshold:
            log.info("below threshold %.2f < %.2f, fallback to chat", conf, self.threshold)
            return None
        return meta

    @staticmethod
    def _safe_parse(raw: str) -> dict:
        """三级兜底 JSON 解析：json.loads → 正则抓 {...} → {}。"""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            return {}

    @staticmethod
    def _build_user_msg(user_input: str, history: list[dict] | None) -> str:
        """带最近几轮历史，帮助消歧（如"再做一个"）。"""
        lines: list[str] = []
        if history:
            for h in history[-4:]:
                lines.append(f"{h['role']}: {h['content']}")
            lines.append("---")
        lines.append(f"当前用户输入：{user_input}")
        return "\n".join(lines)
