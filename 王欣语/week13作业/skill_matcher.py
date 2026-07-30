"""
意图匹配引擎

负责根据用户输入，匹配最合适的 Skill。

匹配策略（分层递进）：
1. 精确匹配：用户输入直接包含 trigger 关键词
2. 模糊匹配：计算输入与 trigger 的相似度
3. 描述匹配：与 Skill description 做关键词匹配
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

from skill_loader import SkillMeta

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """匹配结果"""

    skill: SkillMeta
    score: float  # 0~1，越高越匹配
    matched_trigger: str = ""  # 命中的 trigger
    match_type: str = ""  # 匹配类型：exact / fuzzy / description


class SkillMatcher:
    """
    Skill 意图匹配器

    支持两种模式：
    - 关键词模式：基于 trigger 列表的精确/模糊匹配
    - 语义模式：基于 description 的关键词覆盖度
    """

    def __init__(self, threshold: float = 0.3):
        self.threshold = threshold

    def match(self, user_input: str, skills: list[SkillMeta]) -> list[MatchResult]:
        """
        匹配用户输入与 Skill 列表

        Args:
            user_input: 用户输入文本
            skills: 待匹配的 Skill 列表

        Returns:
            按分数降序排列的匹配结果列表
        """
        results = []
        normalized_input = self._normalize(user_input)

        for skill in skills:
            result = self._match_skill(normalized_input, skill)
            if result and result.score >= self.threshold:
                results.append(result)

        # 按分数降序排列
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _match_skill(self, normalized_input: str, skill: SkillMeta) -> Optional[MatchResult]:
        """
        匹配单个 Skill

        策略优先级：
        1. 精确匹配 trigger（输入包含 trigger）
        2. 模糊匹配 trigger（编辑距离/相似度）
        3. 描述关键词匹配
        """
        best_score = 0.0
        best_trigger = ""
        match_type = ""

        # 1. 精确匹配 triggers
        for trigger in skill.triggers:
            normalized_trigger = self._normalize(trigger)
            if normalized_trigger in normalized_input:
                score = 1.0
                if score > best_score:
                    best_score = score
                    best_trigger = trigger
                    match_type = "exact"

        # 2. 模糊匹配 triggers
        if best_score < 1.0:
            for trigger in skill.triggers:
                normalized_trigger = self._normalize(trigger)
                score = self._fuzzy_score(normalized_input, normalized_trigger)
                if score > best_score:
                    best_score = score
                    best_trigger = trigger
                    match_type = "fuzzy"

        # 3. 描述关键词匹配（作为补充）
        if best_score < 0.5:
            desc_score = self._description_score(normalized_input, skill)
            if desc_score > best_score:
                best_score = desc_score
                best_trigger = ""
                match_type = "description"

        if best_score <= 0:
            return None

        return MatchResult(
            skill=skill,
            score=round(best_score, 3),
            matched_trigger=best_trigger,
            match_type=match_type,
        )

    def _normalize(self, text: str) -> str:
        """
        文本标准化：小写、去除多余空格、去除标点
        """
        text = text.lower().strip()
        # 去除常见标点
        text = re.sub(r'[\u3000-\u303f\uff00-\uffef.,?!;:\\\"\'()\[\]]', " ", text)
        # 合并多个空格
        text = re.sub(r"\s+", " ", text)
        return text

    def _fuzzy_score(self, input_text: str, trigger: str) -> float:
        """
        计算模糊匹配分数（基于字符重叠度）

        使用简单的 Jaccard 相似度变体：
        score = 2 * |A ∩ B| / (|A| + |B|)
        """
        if not input_text or not trigger:
            return 0.0

        # 使用字符集合计算重叠
        input_chars = set(input_text)
        trigger_chars = set(trigger)

        intersection = len(input_chars & trigger_chars)
        union = len(input_chars | trigger_chars)

        if union == 0:
            return 0.0

        # 基础 Jaccard
        jaccard = intersection / union

        # 额外奖励：trigger 是输入的子串（但可能中间有空格差异）
        # 检查 trigger 中的每个词是否在输入中出现
        trigger_words = trigger.split()
        matched_words = sum(1 for w in trigger_words if w in input_text)
        word_coverage = matched_words / len(trigger_words) if trigger_words else 0

        # 综合分数：Jaccard 占 40%，词覆盖度占 60%
        score = jaccard * 0.4 + word_coverage * 0.6
        return min(score, 0.95)  # 模糊匹配最高 0.95，不如精确匹配的 1.0

    def _description_score(self, input_text: str, skill: SkillMeta) -> float:
        """
        基于 Skill description 的关键词匹配

        提取 description 中的关键词，计算与输入的重叠度
        """
        if not skill.description:
            return 0.0

        desc_normalized = self._normalize(skill.description)

        # 提取关键词（长度 > 1 的词）
        desc_words = set(w for w in desc_normalized.split() if len(w) > 1)
        input_words = set(w for w in input_text.split() if len(w) > 1)

        if not desc_words:
            return 0.0

        # 计算重叠
        matched = len(desc_words & input_words)
        score = matched / len(desc_words) * 0.5  # 描述匹配最高 0.5

        return score
