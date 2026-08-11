# -*- coding: utf-8 -*-
"""
一线值班助手 Agent：使用当前 Skills 回答值班工程师的处置咨询，并记录每次调用的 token 用量。

"""

import os
from openai import OpenAI
from skill_manager import SkillManager


SYSTEM_TEMPLATE = """你是「监控平台」的一线值班助手，负责协助值班工程师判断故障定级、
升级路径、变更回滚授权、对外沟通时限和事后总结要求。

你的所有知识来源于以下技能文档，严格基于文档内容回答，不要自行推断或编造处置规则。

## 回答规则（严格遵守）
- 【能回答】如果技能文档覆盖了用户问题：直接给出完整具体的答案（含具体分钟数/小时数/
  工作日数等处置细节）。**不要在答案中加"建议人工判定"之类的推脱话**。
- 【不能回答】如果技能文档确实不覆盖：**仅回答一句** "需要人工判定"，
  不要编造答案，也不要列举可能的情况。

{skills_section}
"""

SKILLS_SECTION_TEMPLATE = """## 当前知识库（共{count}个技能）

{skills_content}
"""


class OncallAssistantAgent:
    def __init__(
        self,
        skill_manager: SkillManager,
        model: str = "deepseek-v4-flash",
    ):
        self.skill_manager = skill_manager
        self.model = model
        self.conversation_history: list[dict] = []
        self.last_usage: dict = {}
        self.cumulative_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )

    def answer(self, question: str) -> str:
        """
        回答单个问题。每次调用都会重新加载最新 Skills（保证 Nudge 后立即生效），
        且 messages 里只含系统提示 + 当前问题（不携带 conversation_history）。
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self._build_system_prompt()},
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

        self.conversation_history.append({
            "question": question,
            "answer": answer_text,
            "skills_used": list(self.skill_manager.load_all().keys()),
        })
        if len(self.conversation_history) > 50:
            self.conversation_history = self.conversation_history[-50:]

        return answer_text

    def _build_system_prompt(self) -> str:
        skills = self.skill_manager.load_all()
        if not skills:
            skills_section = "（暂无技能文档，请依据通用值班原则回答）"
        else:
            parts = []
            for name, content in sorted(skills.items()):
                parts.append(f"### 技能：{name}\n{content}")
            skills_content = "\n\n---\n\n".join(parts)
            skills_section = SKILLS_SECTION_TEMPLATE.format(
                count=len(skills),
                skills_content=skills_content,
            )
        return SYSTEM_TEMPLATE.format(skills_section=skills_section)
