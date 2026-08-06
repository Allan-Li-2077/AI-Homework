"""
反馈分析器：从用户反馈中识别模式和 Skill 改进方向。

核心工作：
  1. 聚类分析：将相似反馈归类（缺少使用场景、缺少对比、格式问题等）
  2. 优先级排序：按出现频次和重要性排序改进点
  3. 生成改进建议：告诉优化器应该在 Skill 的哪里做改动

使用方式：
  from skill_optimize.feedback_analyzer import FeedbackAnalyzer
  analyzer = FeedbackAnalyzer()
  patterns = analyzer.analyze(feedback_list)
  # patterns = [{"category": "缺少使用场景", "count": 5, "examples": [...], "suggestion": "..."}]
"""

import re
from typing import Optional
from collections import defaultdict


# 预定义的反馈类别和对应的 Skill 改进模式
FEEDBACK_CATEGORIES = {
    "缺少使用场景": {
        "keywords": ["使用场景", "例句", "例子", "用法", "如何使用", "怎么用"],
        "skill_section": "内容要求",
        "suggestion": "在生成内容时增加使用场景/例句部分",
    },
    "缺少对比": {
        "keywords": ["对比", "英式", "美式", "区别", "差异", "不同"],
        "skill_section": "内容要求",
        "suggestion": "增加对比维度（英式vs美式、正误对比等）",
    },
    "缺少语法说明": {
        "keywords": ["语法", "词性", "时态", "单复数", "变形"],
        "skill_section": "内容要求",
        "suggestion": "增加语法/词法说明部分",
    },
    "缺少发音信息": {
        "keywords": ["发音", "音标", " pronunciation", "重音"],
        "skill_section": "内容要求",
        "suggestion": "增加发音信息（音标、重音位置）",
    },
    "格式不清晰": {
        "keywords": ["格式", "排版", "乱", "不清楚", "看不懂"],
        "skill_section": "输出格式",
        "suggestion": "优化输出格式和排版结构",
    },
    "内容不准确": {
        "keywords": ["错误", "不对", "不准确", "纠正"],
        "skill_section": "知识准确性",
        "suggestion": "核对并修正内容准确性",
    },
    "信息太少": {
        "keywords": ["太少", "过于简单", "内容不足", "太简略"],
        "skill_section": "内容深度",
        "suggestion": "增加更丰富的内容细节",
    },
    "重复内容": {
        "keywords": ["重复", "冗余", "多余"],
        "skill_section": "内容去重",
        "suggestion": "避免生成重复内容",
    },
}


class FeedbackPattern:
    """一个识别出的反馈模式"""

    def __init__(
        self,
        category: str,
        count: int,
        examples: list[dict],
        suggestion: str,
        skill_section: str,
    ):
        self.category = category
        self.count = count
        self.examples = examples
        self.suggestion = suggestion
        self.skill_section = skill_section

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "count": self.count,
            "examples": self.examples,
            "suggestion": self.suggestion,
            "skill_section": self.skill_section,
        }


class FeedbackAnalyzer:
    """
    分析用户反馈，识别模式和改进方向。

    分析流程：
    1. 对每条反馈进行分类（匹配预定义类别或归为"其他"）
    2. 统计每个类别的出现频次
    3. 提取每类的典型示例
    4. 生成针对 Skill 的改进建议
    """

    def __init__(self):
        self.categories = FEEDBACK_CATEGORIES

    def analyze(self, feedback_list: list) -> list[FeedbackPattern]:
        """
        分析反馈列表，返回识别出的模式列表（按频次降序）
        """
        # 按类别分组
        categorized: dict[str, list] = defaultdict(list)
        uncategorized = []

        for fb in feedback_list:
            matched = self._categorize(fb)
            if matched:
                categorized[matched].append(fb)
            else:
                uncategorized.append(fb)

        # 构建模式列表
        patterns = []
        for category, entries in sorted(categorized.items(), key=lambda x: len(x[1]), reverse=True):
            cat_info = self.categories.get(category, {})
            pattern = FeedbackPattern(
                category=category,
                count=len(entries),
                examples=[self._to_example(e) for e in entries[:3]],  # 最多3个示例
                suggestion=cat_info.get("suggestion", "需要改进"),
                skill_section=cat_info.get("skill_section", "内容要求"),
            )
            patterns.append(pattern)

        # 处理未分类的反馈
        if uncategorized:
            pattern = FeedbackPattern(
                category="其他（需人工审核）",
                count=len(uncategorized),
                examples=[self._to_example(e) for e in uncategorized[:3]],
                suggestion="人工审核这些反馈，决定是否需要改进 Skill",
                skill_section="待定",
            )
            patterns.append(pattern)

        return patterns

    def _categorize(self, feedback) -> Optional[str]:
        """将反馈分类到预定义类别之一"""
        text = feedback.feedback_text if hasattr(feedback, "feedback_text") else str(feedback)
        text_lower = text.lower()

        for category, info in self.categories.items():
            for keyword in info["keywords"]:
                if keyword in text_lower:
                    return category
        return None

    def _to_example(self, feedback) -> dict:
        """提取反馈的示例信息"""
        if hasattr(feedback, "to_dict"):
            d = feedback.to_dict()
            return {
                "feedback": d["feedback_text"],
                "user_input": d.get("user_input", "")[:100],
                "timestamp": d.get("timestamp", ""),
            }
        return {"feedback": str(feedback)}

    def get_top_improvements(self, patterns: list[FeedbackPattern], top_n: int = 3) -> list[str]:
        """
        从模式列表中提取最需要改进的 top_n 项，
        返回简化的建议列表。
        """
        suggestions = []
        for p in patterns[:top_n]:
            suggestions.append(f"[{p.category}] {p.suggestion}")
        return suggestions


class LLMFeedbackAnalyzer(FeedbackAnalyzer):
    """
    基于 LLM 的反馈分析器（可选升级版）。

    当预定义类别无法覆盖时，使用 LLM 来：
    1. 理解反馈的真实意图
    2. 判断应该修改 Skill 的哪个部分
    3. 生成具体的修改建议

    使用方式：
        analyzer = LLMFeedbackAnalyzer(api_key="...")
        patterns = analyzer.analyze_with_llm(feedback_list)
    """

    SYSTEM_PROMPT = """你是一个 Skill 改进专家。你的任务是根据用户反馈分析 Skill 需要改进的地方。

反馈来自用户真实使用体验，可能包含：
- 用户说"缺少 XXX" → Skill 需要增加 XXX
- 用户说"XXX 不对" → Skill 需要修正 XXX
- 用户说"格式乱" → Skill 的输出格式规则需要改进

请分析反馈，判断：
1. 反馈属于哪个类别
2. 应该修改 Skill 的哪个部分（哪个章节/规则）
3. 建议的具体修改方向

只输出 JSON，不要有其他文字。"""

    USER_PROMPT = """## 用户反馈列表（共 {n} 条）：

{feedback_text}

## 当前 Skill 内容：
{skill_content}

请分析并返回 JSON：
{{
  "patterns": [
    {{
      "category": "反馈类别",
      "count": 该类别出现次数,
      "examples": [典型反馈示例],
      "skill_section": "应修改的 Skill 章节",
      "suggestion": "具体修改建议"
    }}
  ]
}}"""

    def __init__(self, api_key: str, model: str = "deepseek-chat", base_url: str = "https://api.deepseek.com"):
        super().__init__()
        import os
        os.environ.setdefault("DEEPSEEK_API_KEY", api_key)
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def analyze_with_llm(
        self,
        feedback_list: list,
        skill_content: str,
    ) -> list[FeedbackPattern]:
        """
        使用 LLM 分析反馈，需要传入 Skill 的完整内容以便给出具体建议。
        """
        from openai import OpenAI

        feedback_text = "\n".join(
            f"- [{fb.feedback_type}] {fb.feedback_text}"
            for fb in feedback_list
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": self.USER_PROMPT.format(
                    n=len(feedback_list),
                    feedback_text=feedback_text,
                    skill_content=skill_content,
                )},
            ],
            temperature=0,
            max_tokens=2000,
        )

        import json, re
        raw = response.choices[0].message.content.strip()
        try:
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                patterns = []
                for p in data.get("patterns", []):
                    patterns.append(FeedbackPattern(
                        category=p.get("category", "未知"),
                        count=p.get("count", 1),
                        examples=p.get("examples", []),
                        suggestion=p.get("suggestion", ""),
                        skill_section=p.get("skill_section", "内容要求"),
                    ))
                return patterns
        except Exception as e:
            print(f"  [LLMFeedbackAnalyzer] 解析失败: {e}")

        # fallback 到基础分析
        return self.analyze(feedback_list)
