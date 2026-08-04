"""
Skill Matcher — 三层意图匹配（从快到慢、从省到贵）

教学重点：
  1. 三层匹配策略渐进升级，避免不必要的 LLM 调用
  2. Tier 1: 显式命令匹配（零成本）
  3. Tier 2: 关键词匹配（极低成本，~1ms）
  4. Tier 3: LLM 语义匹配（按需使用，仅在模糊场景触发）

使用方式：
    matcher = SkillMatcher(registry)
    results = matcher.match("画个架构图")  # 返回 list[MatchResult]
"""

import re
import logging

from .models import SkillMeta, Skill, MatchResult
from .registry import SkillRegistry

logger = logging.getLogger(__name__)

# 匹配得分阈值
COMMAND_CONFIDENCE = 1.0       # Tier 1 命令匹配
KEYWORD_CONFIDENCE_BASE = 0.5  # Tier 2 关键词基础分
KEYWORD_THRESHOLD = 0.2        # Tier 2 最低阈值
LLM_CONFIDENCE_BASE = 0.4      # Tier 3 LLM 匹配置信度


class SkillMatcher:
    """
    三层匹配器。

    匹配策略（auto 模式下自动逐级尝试）：
      Tier 1 — 命令匹配：检测 /skill-name 格式，直接精确查找
      Tier 2 — 关键词匹配：用户分词 vs skill name+description
      Tier 3 — LLM 匹配：用 LLM 判断用户意图（仅在 Tier 1/2 未命中时）
    """

    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self._llm_matcher = None  # 延迟创建 LLM client

    def match(
        self,
        user_input: str,
        top_k: int = 3,
        strategy: str = "auto",
    ) -> list[MatchResult]:
        """
        对用户输入执行技能匹配。

        Args:
            user_input: 用户输入文本
            top_k: 最多返回前 K 个结果
            strategy: "command" | "keyword" | "llm" | "auto"

        Returns:
            按得分降序排列的匹配结果列表
        """
        if not self.registry.is_discovered:
            logger.warning("Registry 尚未 discover，匹配结果为空")
            return []

        user_input_stripped = user_input.strip()
        if not user_input_stripped:
            return []

        strategies = self._resolve_strategies(strategy)

        for s in strategies:
            if s == "command":
                result = self._match_command(user_input_stripped)
                if result:
                    return [result]

            elif s == "keyword":
                results = self._match_keyword(user_input_stripped, top_k)
                if results and results[0].score >= KEYWORD_THRESHOLD:
                    return results
                # keyword 未达阈值：如果还有 LLM 策略，继续尝试
                if "llm" in strategies and results:
                    # 保留 keyword 结果作为 fallback，继续尝试 LLM
                    pass

            elif s == "llm":
                results = self._match_llm(user_input_stripped, top_k)
                if results:
                    return results

        # 兜底: 返回 keyword 结果（即使低于阈值）
        return self._match_keyword(user_input_stripped, top_k)

    # ── Tier 1: 命令匹配 ────────────────────────────────────────────

    def _match_command(self, user_input: str) -> MatchResult | None:
        """
        Tier 1: 检测 /skill-name 格式的显式命令。

        示例: "/baoyu-diagram" → 直接匹配 baoyu-diagram
              "/flash-card 做个关于 crazy 的" → 匹配 flash-card
        """
        # 检测以 / 开头的命令
        m = re.match(r"^/([\w-]+)", user_input)
        if not m:
            return None

        cmd_name = m.group(1).lower()
        meta = self.registry.get(cmd_name)
        if meta:
            logger.info(f"[Matcher] Tier 1 命令匹配: /{cmd_name}")
            return MatchResult(
                skill=Skill(meta=meta),
                score=COMMAND_CONFIDENCE,
                match_type="command",
                matched_keywords=[f"/{cmd_name}"],
            )

        # 尝试模糊匹配（用户可能拼错）
        for name, meta in self.registry._skills.items():
            if cmd_name in name or name in cmd_name:
                logger.info(f"[Matcher] Tier 1 模糊命令匹配: /{cmd_name} → {name}")
                return MatchResult(
                    skill=Skill(meta=meta),
                    score=0.9,
                    match_type="command",
                    matched_keywords=[f"/{cmd_name}"],
                )

        return None

    # ── Tier 2: 关键词匹配 ──────────────────────────────────────────

    def _match_keyword(self, user_input: str, top_k: int = 3) -> list[MatchResult]:
        """
        Tier 2: 基于 name + description 的关键词匹配。

        算法（覆盖率优先，适应长描述场景）：
          1. 对用户输入提取中英文关键词
          2. 对每个 skill 的 name + description 提取关键词
          3. 计算覆盖率得分:
             - recall = |overlap| / |user_keywords|      (用户关键词命中率, 权重 0.6)
             - precision = |overlap| / |target_keywords|  (目标关键词覆盖率, 权重 0.1)
             - name_bonus: skill name 直接命中时 +0.3
          4. 按得分降序返回 top_k
        """
        user_keywords = self._extract_keywords(user_input.lower())
        if not user_keywords:
            return []

        results = []
        user_lower = user_input.lower()

        for name, meta in self.registry._skills.items():
            target_text = f"{name} {meta.description}".lower()
            target_keywords = self._extract_keywords(target_text)

            if not target_keywords:
                continue

            overlap = user_keywords & target_keywords

            # 名称命中奖励（即使无关键词重叠也能生效）
            name_bonus = 0.0
            name_lower = name.lower()
            name_no_hyphen = name_lower.replace("-", "")
            user_no_hyphen = user_lower.replace("-", "")
            name_parts = [p for p in name_lower.replace("-", " ").split() if len(p) >= 3]

            # 精确名称匹配
            if name_lower in user_lower:
                name_bonus = 0.3
                overlap = overlap | {"[name_exact]"}
            # 去连字符匹配（"flashcard" 匹配 "flash-card"）
            elif name_no_hyphen in user_no_hyphen:
                name_bonus = 0.25
                overlap = overlap | {"[name_nohyphen]"}
            # 名称部分匹配（如 "diagram"、"flash"、"card"）
            elif any(part in user_lower for part in name_parts):
                name_bonus = 0.15
                matched_parts = [p for p in name_parts if p in user_lower]
                overlap = overlap | set(matched_parts)

            # 无重叠且无名称匹配，跳过
            if not overlap:
                continue

            # 覆盖率得分: 侧重用户关键词命中率 (recall-oriented)
            recall = len(overlap) / len(user_keywords)
            precision = len(overlap) / len(target_keywords) if target_keywords else 0
            base_score = recall * 0.8 + precision * 0.05

            score = min(base_score + name_bonus, 1.0)
            if score >= KEYWORD_THRESHOLD:
                results.append(MatchResult(
                    skill=Skill(meta=meta),
                    score=round(score, 3),
                    match_type="keyword",
                    matched_keywords=list(overlap),
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        logger.info(
            f"[Matcher] Tier 2 关键词匹配: "
            f"{[(r.skill.meta.name, r.score) for r in results[:top_k]]}"
        )
        return results[:top_k]

    # ── Tier 3: LLM 语义匹配 ────────────────────────────────────────

    def _match_llm(self, user_input: str, top_k: int = 3) -> list[MatchResult]:
        """
        Tier 3: 使用 LLM 进行语义匹配。

        仅在 Tier 1/2 无法明确匹配时调用（成本较高）。
        """
        skills_summary = "\n".join(
            f"- {meta.name}: {meta.description[:100]}"
            for meta in self.registry.list_skills()
        )

        if not skills_summary:
            return []

        prompt = (
            "你是一个技能匹配助手。根据用户的输入，判断最适合使用以下哪个技能。\n\n"
            f"可用技能：\n{skills_summary}\n\n"
            f"用户输入：\"{user_input}\"\n\n"
            "请只返回最适合的技能名称（精确匹配上面的名称），"
            "如果没有合适的技能，返回 \"none\"。\n"
            "只返回技能名称或 none，不要多余文字。"
        )

        try:
            from .llm_config import get_chat_client
            client, model = get_chat_client()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=50,
            )
            skill_name = response.choices[0].message.content.strip().lower()

            if skill_name == "none" or not skill_name:
                logger.info("[Matcher] Tier 3 LLM 匹配: 无匹配")
                return []

            meta = self.registry.get(skill_name)
            if meta:
                logger.info(f"[Matcher] Tier 3 LLM 匹配: {skill_name}")
                return [MatchResult(
                    skill=Skill(meta=meta),
                    score=LLM_CONFIDENCE_BASE,
                    match_type="llm",
                    matched_keywords=["llm_semantic"],
                )]

        except Exception as e:
            logger.warning(f"[Matcher] Tier 3 LLM 匹配失败: {e}")

        return []

    # ── 工具方法 ────────────────────────────────────────────────────

    @staticmethod
    def _resolve_strategies(strategy: str) -> list[str]:
        """解析匹配策略"""
        if strategy == "auto":
            return ["command", "keyword", "llm"]
        return [strategy]

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """
        提取中英文关键词。

        中文：使用 2-gram + 3-gram 滑动窗口分词
              （不引入 jieba 等分词库，零依赖方案）
              例如 "画个架构图" → {"画个", "个架", "架构", "构图", "画个架", "个架构", "架构图"}
        英文：按非字母数字字符分词
        """
        keywords = set()

        # 1. 英文单词
        for w in re.findall(r"[a-zA-Z0-9]+", text):
            if len(w) > 1:
                keywords.add(w.lower())

        # 2. 中文 n-gram（2-gram + 3-gram 滑动窗口）
        # 先提取连续的中文片段
        chinese_spans = re.findall(r"[一-鿿㐀-䶿豈-﫿]+", text)
        for span in chinese_spans:
            span_len = len(span)
            # 2-gram
            for i in range(span_len - 1):
                keywords.add(span[i:i + 2])
            # 3-gram（仅对较长的中文片段）
            if span_len >= 3:
                for i in range(span_len - 2):
                    keywords.add(span[i:i + 3])
            # 4-gram（仅对更长的片段）
            if span_len >= 4:
                for i in range(span_len - 3):
                    keywords.add(span[i:i + 4])

        # 过滤掉长度 < 2 的
        return {w for w in keywords if len(w) >= 2}
