"""
SkillMatcher - 意图匹配引擎

渐进式加载第三阶段:
- 正则/关键词初筛（零成本快速匹配）
- 可选LLM二次判断（提高准确率）
- 返回匹配结果（置信度、匹配原因）

教学重点:
1. 多级匹配策略（规则先行，LLM兜底）
2. 置信度评分
3. 匹配结果解释性
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

from .skill_registry import SkillRegistry, SkillMeta
from .skill_loader import SkillLoader, SkillContent

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Skill匹配结果"""
    skill_name: str                              # 匹配到的skill名称
    confidence: float = 0.0                     # 置信度 (0-1)
    match_type: str = "keyword"                 # 匹配类型: keyword/description/llm
    matched_terms: list[str] = field(default_factory=list)  # 匹配到的关键词
    reason: str = ""                             # 匹配原因说明
    
    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.7
    
    @property
    def is_medium_confidence(self) -> bool:
        return 0.4 <= self.confidence < 0.7
    
    @property
    def is_low_confidence(self) -> bool:
        return self.confidence < 0.4


class SkillMatcher:
    """
    Skill意图匹配器
    
    采用多级匹配策略:
    1. 关键词初筛（快速，零成本）
    2. 描述匹配（中等成本）
    3. 可选LLM判断（高成本，高精度）
    """
    
    # 内置的关键词映射（通用触发词）
    KEYWORD_MAP: dict[str, list[str]] = {
        "flash-card": ["闪卡", "flashcard", "flash card", "单词卡", "词汇卡", "word card", "vocabulary"],
        "baoyu-diagram": ["图表", "diagram", "chart", "画图", "架构图", "流程图", "时序图", "结构图"],
        "hello-world": ["hello", "你好", "测试", "test", "示例", "demo"],
    }
    
    def __init__(
        self,
        registry: SkillRegistry,
        loader: SkillLoader,
        use_llm: bool = False,
    ):
        self.registry = registry
        self.loader = loader
        self.use_llm = use_llm
        self._match_count = 0
    
    def match(self, user_input: str) -> Optional[MatchResult]:
        """
        匹配用户输入到对应Skill
        
        渐进式匹配:
        1. 先用关键词快速匹配（零成本）
        2. 再用description模糊匹配
        3. 可选LLM精确判断
        """
        if not user_input or not user_input.strip():
            return None
        
        input_lower = user_input.lower().strip()
        self._match_count += 1
        
        # Phase 1: 关键词初筛
        keyword_result = self._keyword_match(input_lower, user_input)
        if keyword_result and keyword_result.is_high_confidence:
            logger.info(f"关键词匹配命中: {keyword_result.skill_name} (置信度: {keyword_result.confidence:.2f})")
            return keyword_result
        
        # Phase 2: 描述匹配
        desc_result = self._description_match(input_lower, user_input)
        if desc_result and desc_result.confidence > 0.3:
            if not keyword_result or desc_result.confidence > keyword_result.confidence:
                logger.info(f"描述匹配命中: {desc_result.skill_name} (置信度: {desc_result.confidence:.2f})")
                return desc_result
        
        # 返回最高置信度的结果
        best = keyword_result or desc_result
        if best:
            return best
        
        return None
    
    def match_all(self, user_input: str, top_k: int = 3) -> list[MatchResult]:
        """
        匹配所有可能的Skills（返回top-k）
        """
        if not user_input or not user_input.strip():
            return []
        
        input_lower = user_input.lower().strip()
        results: list[MatchResult] = []
        
        for skill in self.registry:
            score, terms = self._score_skill(input_lower, skill, user_input)
            if score > 0.1:
                result = MatchResult(
                    skill_name=skill.name,
                    confidence=score,
                    match_type="hybrid",
                    matched_terms=terms,
                    reason=self._build_reason(skill, terms, score),
                )
                results.append(result)
        
        results.sort(key=lambda r: r.confidence, reverse=True)
        return results[:top_k]
    
    def _keyword_match(self, input_lower: str, original: str) -> Optional[MatchResult]:
        """关键词精确匹配"""
        best_result = None
        best_score = 0
        
        for skill in self.registry:
            keywords = self.KEYWORD_MAP.get(skill.name, [])
            
            # 从skill描述中提取关键短语
            desc_keywords = self._extract_keywords(skill.description)
            keywords.extend(desc_keywords)
            
            matched = []
            for kw in keywords:
                if kw.lower() in input_lower:
                    matched.append(kw)
            
            if matched:
                # 置信度计算：匹配数量 / 总关键词数
                score = min(1.0, len(matched) / max(3, len(keywords)) * 0.8 + 0.2 * len(matched))
                score = min(1.0, score)
                
                result = MatchResult(
                    skill_name=skill.name,
                    confidence=score,
                    match_type="keyword",
                    matched_terms=matched,
                    reason=f"关键词匹配: 命中 {len(matched)} 个关键词 [{', '.join(matched)}]",
                )
                
                if score > best_score:
                    best_score = score
                    best_result = result
        
        return best_result
    
    def _description_match(self, input_lower: str, original: str) -> Optional[MatchResult]:
        """基于描述的模糊匹配"""
        best_result = None
        best_score = 0
        
        for skill in self.registry:
            desc_lower = skill.description.lower()
            words = input_lower.split()
            
            matched_words = []
            score = 0
            
            for word in words:
                if len(word) > 2 and word in desc_lower:
                    matched_words.append(word)
                    score += 0.2
            
            if matched_words:
                score = min(1.0, score)
                result = MatchResult(
                    skill_name=skill.name,
                    confidence=score,
                    match_type="description",
                    matched_terms=matched_words,
                    reason=f"描述匹配: 输入中的 {len(matched_words)} 个词在描述中命中",
                )
                
                if score > best_score:
                    best_score = score
                    best_result = result
        
        return best_result
    
    def _score_skill(self, input_lower: str, skill: SkillMeta, original: str) -> tuple[float, list[str]]:
        """计算单个skill的匹配分数"""
        score = 0.0
        matched_terms = []
        
        # 关键词匹配
        keywords = self.KEYWORD_MAP.get(skill.name, [])
        desc_keywords = self._extract_keywords(skill.description)
        all_keywords = keywords + desc_keywords
        
        for kw in all_keywords:
            if kw.lower() in input_lower:
                matched_terms.append(kw)
                score += 0.3
        
        # 描述词匹配
        desc_words = set(re.findall(r'[a-zA-Z\u4e00-\u9fff]+', skill.description.lower()))
        input_words = set(re.findall(r'[a-zA-Z\u4e00-\u9fff]+', input_lower))
        
        word_overlap = desc_words & input_words
        if word_overlap:
            score += 0.2 * len(word_overlap) / max(1, len(input_words))
            matched_terms.extend(list(word_overlap))
        
        # 名称匹配
        if skill.name.lower() in input_lower:
            score += 0.5
            matched_terms.append(skill.name)
        
        return min(1.0, score), matched_terms
    
    def _extract_keywords(self, text: str) -> list[str]:
        """从描述中提取关键短语"""
        # 提取引号内的内容
        quoted = re.findall(r'[""「](.+?)[""」]', text)
        # 提取逗号分隔的关键词
        parts = re.split(r'[，,、；;]', text)
        
        keywords = []
        for part in quoted + parts:
            part = part.strip()
            if 2 <= len(part) <= 20:
                keywords.append(part)
        
        return list(set(keywords))
    
    def _build_reason(self, skill: SkillMeta, terms: list[str], score: float) -> str:
        """构建匹配原因说明"""
        reasons = []
        if terms:
            reasons.append(f"匹配关键词: [{', '.join(terms[:5])}]")
        reasons.append(f"置信度: {score:.0%}")
        return "; ".join(reasons)
    
    @property
    def match_count(self) -> int:
        """累计匹配次数"""
        return self._match_count
    
    @property
    def skills_available(self) -> int:
        """可用skill数量"""
        return self.registry.count
