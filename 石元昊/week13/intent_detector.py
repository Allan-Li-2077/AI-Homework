"""
Intent Detector — 用户意图 → Skill 匹配

教学重点：
  1. 两层匹配策略：
     - Layer A：关键词/正则快速过滤（零成本，毫秒级）
     - Layer B：LLM 语义判断（精确，但需要 API 调用）
  2. 渐进式信息暴露：
     - Layer A 只暴露 skill name + description 一句话
     - Layer B 才加载完整 SKILL.md（Level 1）
  3. 置信度评分：返回 Top-K 候选 + 置信度，让上层决定是否执行

使用方式：
  detector = IntentDetector(registry)
  matches = detector.detect("帮我画一个微服务架构图")
  # [{"skill": "baoyu-diagram", "confidence": 0.95, "reason": "..."}]
"""

import re
import json
import logging
from dataclasses import dataclass

from src.skill_registry import SkillRegistry
from src.llm_config import get_chat_client

logger = logging.getLogger(__name__)


@dataclass
class SkillMatch:
    """意图匹配结果"""
    skill_name: str
    confidence: float     # 0.0 ~ 1.0
    reason: str           # 匹配原因说明
    match_layer: str      # "keyword" | "llm"

    def __repr__(self):
        return f"SkillMatch({self.skill_name}, {self.confidence:.0%}, {self.match_layer})"


# ── 每个 skill 的关键词快速匹配表 ────────────────────────────────────────────
# 实际项目中可以从 SKILL.md 自动提取，这里手动定义以保证精度
KEYWORD_RULES: dict[str, list[re.Pattern]] = {
    "baoyu-diagram": [
        re.compile(r"画.*(图|架构|流程|时序|结构|思维导图|时间线|状态机|数据流)"),
        re.compile(r"(diagram|flowchart|sequence|architecture|mind.?map)"),
        re.compile(r"(架构图|流程图|时序图|结构图|思维导图|时间线|状态机|数据流图)"),
        re.compile(r"(可视化|拓扑|组件关系|系统.*图)"),
        re.compile(r"draw.*(?:diagram|chart|graph)"),
    ],
    "flash-card": [
        re.compile(r"(闪卡|单词卡|flash.?card)"),
        re.compile(r"(做一个|生成|帮我做).*的.*(卡|card)"),
        re.compile(r"(单词|词汇).*(学习|记忆|卡片)"),
    ],
}


# ── LLM 意图判断 Prompt ─────────────────────────────────────────────────────
_INTENT_PROMPT = """\
你是一个 Skill 路由助手。根据用户的请求，判断应该调用哪个 Skill。

可用的 Skills：
{skill_list}

用户说："{message}"

请判断：
1. 是否有 Skill 能处理这个请求？
2. 如果有，最匹配的是哪个？置信度多少？

返回 JSON：
{{
  "matched": true/false,
  "skill_name": "匹配的skill名称（matched为false时留空）",
  "confidence": 0.0~1.0,
  "reason": "一句话解释匹配原因"
}}

只返回 JSON，不要其他文字。"""


class IntentDetector:
    """
    意图检测器：关键词快筛 + LLM 精确判断

    使用方式：
      detector = IntentDetector(registry)
      matches = detector.detect("画个架构图")
    """

    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self._keyword_rules = dict(KEYWORD_RULES)

    def detect(self, message: str, use_llm: bool = True) -> list[SkillMatch]:
        """
        检测用户意图，返回匹配结果列表（按置信度降序）。

        流程：
          1. 关键词匹配（Layer A）→ 命中则直接返回高置信度结果
          2. 若无关键词命中且 use_llm=True → LLM 语义判断（Layer B）
        """
        results: list[SkillMatch] = []

        # Layer A：关键词快速匹配
        for skill_name, patterns in self._keyword_rules.items():
            if skill_name not in self.registry.get_skill_names():
                continue
            for pattern in patterns:
                if pattern.search(message):
                    results.append(SkillMatch(
                        skill_name=skill_name,
                        confidence=0.9,
                        reason=f"关键词命中：{pattern.pattern}",
                        match_layer="keyword",
                    ))
                    break  # 同一 skill 只记一次

        if results:
            return sorted(results, key=lambda x: x.confidence, reverse=True)

        # Layer B：LLM 语义判断
        if use_llm:
            llm_match = self._llm_detect(message)
            if llm_match:
                results.append(llm_match)

        return results

    def _llm_detect(self, message: str) -> SkillMatch | None:
        """LLM 语义判断：把所有 skill 的 name+description 给 LLM，让它选"""
        descriptions = self.registry.get_skill_descriptions()
        if not descriptions:
            return None

        skill_list = "\n".join(
            f"- {name}: {desc[:120]}"
            for name, desc in descriptions.items()
        )

        try:
            client, model = get_chat_client()
            resp = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": _INTENT_PROMPT.format(
                        skill_list=skill_list,
                        message=message,
                    ),
                }],
                temperature=0,
            )
            raw = resp.choices[0].message.content.strip()
            data = self._parse_json(raw)

            if not data or not data.get("matched"):
                return None

            skill_name = data.get("skill_name", "")
            if skill_name not in self.registry.get_skill_names():
                logger.warning(f"LLM 返回了未知 skill：{skill_name}")
                return None

            return SkillMatch(
                skill_name=skill_name,
                confidence=min(float(data.get("confidence", 0.5)), 1.0),
                reason=data.get("reason", "LLM 语义匹配"),
                match_layer="llm",
            )
        except Exception as e:
            logger.error(f"LLM 意图检测失败：{e}")
            return None

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
        text = re.sub(r"\n?```$", "", text.strip())
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return None
