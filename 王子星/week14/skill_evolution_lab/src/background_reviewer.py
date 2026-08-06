# -*- coding: utf-8 -*-
"""
后台回顾 Agent：分析近期失败样本，决定创建或修改哪些 Skill 文件。

"""

import os
import json
import re
from openai import OpenAI
from pathlib import Path
from skill_manager import SkillManager


REVIEWER_SYSTEM = """你是「监控平台」故障响应系统的"技能优化专家"（后台回顾 Agent）。

以下给你的全部都是一线值班助手最近一轮中**答错或推脱**的样本。你要做的是用最小改动
修复它们，让下次遇到同类问题能答对。

## 核心原则（严格遵守）

1. **仅修复观察到的失败**：只针对输入样本里出现的问题类型做改动，不要扩展到
   "手册里还有但样本里没出现"的场景
2. **最小改动优先**：
   - 能在已有 Skill 里追加或改一条分支解决的，不要新建 Skill
   - 已有 Skill 但缺的是一整块新规则（比如全新的一类判断逻辑），优先在该 Skill
     目录下**新建一个 reference/*.md 文件**（action=create, file="reference/xxx.md"），
     而不是把内容硬塞进已有的 reference 文件或 SKILL.md 里
   - patch 的 old_text 只包含要改的那几行，不要把整段抄下来重写
3. **聚焦核心**：如果失败涉及多种类型，按失败条数从高到低，**只修复 1~2 类**
   —— 留出进化梯度，不要一次改完所有问题
4. **完全没有对应 Skill 的新领域**（比如从未出现过的规则类别）：新建一个全新 Skill，
   action=create, file="SKILL.md"，内容只写"使用步骤+指向reference文件"的入口，
   具体规则表格另起一个 action 写入 reference/*.md

你拥有完整处置手册，仅用于**核对值班助手答错的具体数字/规则是否与手册一致**，
它是判定标准，不是值班助手的知识补全大纲。

## 完整处置手册（判定标准）
{policies}

## 当前已有 Skill 及其文件结构
{current_skills_summary}

## Skill 文件格式规范（遵循 Anthropic Agent Skills 规范的渐进式披露结构）
- 每个 Skill 是一个目录：skills/{{name}}/SKILL.md 为入口文件，可选 skills/{{name}}/reference/*.md 存放细节规则
- SKILL.md frontmatter 必须包含 name（kebab-case）、description、version（整数，新建时填1）
- SKILL.md 正文简短：说明使用步骤，用 Markdown 链接指向 reference/*.md（如果有）
- reference/*.md 正文用 Markdown 小节+表格组织规则，每条规则给出具体数字/期限，不要写成模糊表述

## 输出格式
{{
  "analysis": "本轮失败 N 条，主要失败类型是 XXX",
  "actions": [
    {{"action": "create", "skill_name": "...", "file": "SKILL.md", "reason": "修复哪条失败",
      "content": "完整SKILL.md（含frontmatter）"}},
    {{"action": "create", "skill_name": "...", "file": "reference/xxx.md", "reason": "修复哪条失败",
      "content": "完整reference文件内容"}},
    {{"action": "patch",  "skill_name": "...", "file": "SKILL.md 或 reference/xxx.md", "reason": "修复哪条失败",
      "old_text": "精确的原始文本", "new_text": "替换文本"}}
  ]
}}

只输出 JSON，不要有其他文字。如果发现失败数其实很少、没有清晰模式，可以只返回
1 条 action 甚至 0 条。"""

REVIEWER_USER = """## 本轮失败样本（共 {n} 条，都是值班助手答错或推脱的）

{history_text}

## 当前 Skill 完整内容（含各文件路径）
{current_skills_full}

按核心原则给出最小必要的修复方案。"""


class BackgroundReviewer:
    def __init__(self, policies_path: str, skill_manager: SkillManager, model: str = "deepseek-v4-flash"):
        self.policies = Path(policies_path).read_text(encoding="utf-8")
        self.skill_manager = skill_manager
        self.model = model
        self.last_analysis = ""
        self.last_usage: dict = {}
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )

    def review(self, failed_turns: list[dict], max_attempts: int = 3) -> list[dict]:
        """
        分析失败样本列表，返回最小必要的 Skill 操作。
        调用方应**仅传入本轮失败的条目**（每条形如 {question, answer, fail_reason}）；
        空列表直接返回 []，不做 LLM 调用。

        LLM 输出偶尔会出现两类问题：(a) 返回空内容 (b) JSON 转义错误导致解析失败。
        两者都通过 response_format=json_object 降低概率，并在解析失败时重试
        最多 max_attempts 次；仍失败则返回 []（不阻塞主流程）。
        """
        if not failed_turns:
            return []

        skills_summary = self._build_skills_summary()
        skills_full = self._build_skills_full()

        system_msg = REVIEWER_SYSTEM.format(
            policies=self.policies,
            current_skills_summary=skills_summary,
        )
        user_msg = REVIEWER_USER.format(
            n=len(failed_turns),
            history_text=self._format_history(failed_turns),
            current_skills_full=skills_full,
        )

        for attempt in range(1, max_attempts + 1):
            raw, usage = self._call_llm(system_msg, user_msg)
            if usage is not None:
                self.last_usage = usage
            if not raw:
                print(f"  [Reviewer] 第{attempt}次尝试返回空内容，{'重试' if attempt < max_attempts else '放弃'}")
                continue
            actions = self._parse_actions(raw)
            if actions is not None:
                return actions
            print(f"  [Reviewer] 第{attempt}次尝试JSON解析失败，{'重试' if attempt < max_attempts else '放弃'}")

        self.last_analysis = ""
        return []

    def _call_llm(self, system_msg: str, user_msg: str) -> tuple[str, dict | None]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=8000,
            response_format={"type": "json_object"},
        )
        usage = getattr(response, "usage", None)
        usage_dict = None
        if usage is not None:
            usage_dict = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
        content = response.choices[0].message.content
        return (content.strip() if content else ""), usage_dict

    def _build_skills_summary(self) -> str:
        skill_dirs = sorted(d.name for d in Path(self.skill_manager.skills_dir).iterdir() if d.is_dir())
        if not skill_dirs:
            return "（暂无已有Skill）"
        lines = []
        for name in skill_dirs:
            skill_md = self.skill_manager.get_file(name, "SKILL.md") or ""
            desc = self._extract_description(skill_md)
            files = self.skill_manager.list_files(name)
            lines.append(f"- {name}: {desc}  [文件: {', '.join(files)}]")
        return "\n".join(lines)

    def _build_skills_full(self) -> str:
        skill_dirs = sorted(d.name for d in Path(self.skill_manager.skills_dir).iterdir() if d.is_dir())
        if not skill_dirs:
            return "（暂无已有Skill）"
        parts = []
        for name in skill_dirs:
            for f in self.skill_manager.list_files(name):
                content = self.skill_manager.get_file(name, f) or ""
                parts.append(f"### {name}/{f}\n{content}")
        return "\n\n---\n\n".join(parts)

    def _format_history(self, turns: list[dict]) -> str:
        lines = []
        for i, t in enumerate(turns, 1):
            lines.append(f"[{i}] 值班工程师: {t['question']}")
            lines.append(f"    值班助手: {t['answer'][:200]}{'...' if len(t['answer']) > 200 else ''}")
            if t.get("fail_reason"):
                lines.append(f"    x 判定：{t['fail_reason']}")
        return "\n".join(lines)

    def _extract_description(self, content: str) -> str:
        m = re.search(r"description:\s*(.+)", content)
        return m.group(1).strip() if m else "(无描述)"

    def _parse_actions(self, raw: str) -> list[dict] | None:
        """解析成功返回 actions 列表（可能为空列表）；解析失败返回 None（供调用方重试）。"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"  [Reviewer] JSON 解析失败: {e}\n原始: {raw[:300]}")
            return None
        self.last_analysis = data.get("analysis", "")
        print(f"  [Reviewer] 分析：{self.last_analysis[:100]}")
        actions = data.get("actions", [])
        for act in actions:
            act.setdefault("file", "SKILL.md")
        return actions
