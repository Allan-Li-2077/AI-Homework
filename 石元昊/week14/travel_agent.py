"""
旅行规划 Agent：基于 Skill 知识库回答用户的旅行问题。

核心设计：
  - 每次调用 answer() 前重新加载最新 Skill（保证优化后立即生效）
  - 内置 token 用量 + 响应时间追踪
  - 返回结构化结果 dict，方便评估器做多维度分析

与参考项目 agent.py 的差异：
  - answer() 返回 dict 而非 str（包含 token、time、answer 等字段）
  - 系统提示词要求 Agent "简洁回答、不啰嗦"，配合冗余度评估
"""

import os
import time
from openai import OpenAI


AGENT_SYSTEM = """你是一位专业的东南亚旅行顾问。

你的知识完全来源于下方提供的旅行指南文档。请基于文档内容回答用户问题。

## 回答规则
1. **准确引用**：回答中的数字（价格、天数、汇率等）必须与文档一致，不要编造
2. **简洁直接**：直接回答问题，不要加"根据我的了解"、"建议您"等冗余套话
3. **结构清晰**：适合时用列表或表格呈现，避免大段散文
4. **诚实边界**：如果文档中没有相关信息，直接说"这个问题我的资料中没有覆盖"

{skill_section}
"""


class TravelAgent:

    def __init__(self, skill_manager, model: str = "deepseek-chat"):
        self.skill_manager = skill_manager
        self.model = model
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )
        # 累计统计
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_time = 0.0
        self._call_count = 0

    def answer(self, question: str) -> dict:
        """
        回答单个问题，返回：
        {
            "answer": str,
            "prompt_tokens": int,
            "completion_tokens": int,
            "total_tokens": int,
            "time_sec": float,
            "answer_chars": int  # 回答字符数（用于衡量冗余度）
        }
        """
        sys_prompt = self._build_prompt()

        t0 = time.time()
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=400,
        )
        elapsed = time.time() - t0

        text = resp.choices[0].message.content.strip()
        pt = resp.usage.prompt_tokens if resp.usage else 0
        ct = resp.usage.completion_tokens if resp.usage else 0

        self._total_prompt_tokens += pt
        self._total_completion_tokens += ct
        self._total_time += elapsed
        self._call_count += 1

        return {
            "answer": text,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": pt + ct,
            "time_sec": round(elapsed, 3),
            "answer_chars": len(text),
        }

    def reset_stats(self):
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_time = 0.0
        self._call_count = 0

    def stats(self) -> dict:
        return {
            "calls": self._call_count,
            "prompt_tokens": self._total_prompt_tokens,
            "completion_tokens": self._total_completion_tokens,
            "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
            "total_time": round(self._total_time, 3),
            "avg_prompt_tokens": round(self._total_prompt_tokens / max(self._call_count, 1), 1),
            "avg_completion_tokens": round(self._total_completion_tokens / max(self._call_count, 1), 1),
            "avg_time": round(self._total_time / max(self._call_count, 1), 3),
        }

    def _build_prompt(self) -> str:
        skills = self.skill_manager.load_all()
        if not skills:
            section = "（暂无旅行指南）"
        else:
            parts = [f"### {name}\n{content}" for name, content in sorted(skills.items())]
            section = "\n\n---\n\n".join(parts)
        return AGENT_SYSTEM.format(skill_section=section)
