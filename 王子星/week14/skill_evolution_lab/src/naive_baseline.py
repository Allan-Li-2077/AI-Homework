# -*- coding: utf-8 -*-
"""
对照组 Agent：不使用 Skill 机制，直接把完整的 policies.md（故障响应处置手册）塞进 system prompt。

"""

import os
from pathlib import Path
from openai import OpenAI


SYSTEM_TEMPLATE = """你是「监控平台」的一线值班助手，负责协助值班工程师判断故障定级、
升级路径、变更回滚授权、对外沟通时限和事后总结要求。

你的所有知识来源于以下完整处置手册，严格基于文档内容回答，不要自行推断或编造处置规则。

## 回答规则（严格遵守）
- 【能回答】如果处置手册覆盖了用户问题：直接给出完整具体的答案（含具体分钟数/小时数/
  工作日数等处置细节）。**不要在答案中加"建议人工判定"之类的推脱话**。
- 【不能回答】如果处置手册确实不覆盖：**仅回答一句** "需要人工判定"，
  不要编造答案，也不要列举可能的情况。

## 完整处置手册
{policies}
"""


class NaiveBaselineAgent:
    def __init__(self, policies_path: str, model: str = "deepseek-v4-flash"):
        self.policies = Path(policies_path).read_text(encoding="utf-8")
        self.model = model
        self.last_usage: dict = {}
        self.cumulative_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )

    def answer(self, question: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_TEMPLATE.format(policies=self.policies)},
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=400,
        )
        answer_text = response.choices[0].message.content.strip()

        usage = getattr(response, "usage", None)
        if usage is not None:
            self.last_usage = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
            for k in self.cumulative_usage:
                self.cumulative_usage[k] += self.last_usage[k]

        return answer_text
