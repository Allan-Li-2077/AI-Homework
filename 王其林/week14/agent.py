"""
自进化 ReAct Agent：根据 Skill + 任务，用 ReAct 循环回答任务，
并在运行中按 Nudge 间隔自动迭代自己的 Skill。

教学重点（对齐 self_evolving_agent 参考项目）：
  1. Agent 的唯一知识来源是 skills/ 下的 Skill 文件，每次 answer() 前动态加载
     最新版（保证进化后立即生效），skills/ 只保留最新版
  2. ReAct 架构：Thought → Action → Observation 循环；Observation 来自环境
     （评估器）反馈，发现问题则修正重出，最多 max_react_rounds 轮
  3. Nudge 计数器：每 nudge_interval 次回答后，把累积的失败样本送入进化 Agent，
     让 Skill 自动迭代（对应 Hermes 的 _iters_since_skill）
  4. 每次调用的 token 消耗从 response.usage 精确统计，用于优化前后对比

使用方式：
  from skill_manager import SkillManager
  from evaluator import Evaluator
  from optimizer import SkillOptimizer
  sm = SkillManager("skills/")
  agent = ReActCodingAgent(sm, Evaluator(tasks), skill_optimizer=SkillOptimizer(sm),
                           nudge_interval=5)
  r = agent.answer("请写出李白《静夜思》的名句...", task)
"""

import os
import time
from openai import OpenAI

import tiktoken

ENC = tiktoken.get_encoding("cl100k_base")

SYSTEM_TEMPLATE = """你是古诗词知识问答 Agent。

你的所有知识来源于以下技能文档，严格基于文档内容回答，**禁止动用你自身的先验知识**。

## 回答规则（严格遵守）
- 【能回答】如果技能文档覆盖了任务考察的知识点：直接给出完整具体的答案（含具体诗名/人名/
  字号/原句/术语等细节），分点结构化输出。**不要在答案中加"建议查阅相关资料"之类的推脱话**。
- 【不能回答】如果技能文档确实不涵盖该知识点：**仅回答一句** "技能文档未涵盖此知识点"，
  不要编造答案，不要列举可能的情况，更不要动用你自身的先验知识补充。

## ReAct 工作流（严格遵守）
对每个任务循环执行，最多 {max_react_rounds} 轮：
- Thought：分析任务考察的知识点，**先检查技能文档中是否有对应内容**，再决定能否回答
- Action：若技能文档覆盖则输出完整结构化回答；若未覆盖则输出"技能文档未涵盖此知识点"
- Observation：观察自检结果；若回答遗漏关键知识点，基于观察修正后重新输出完整回答

{skills_section}
"""

SKILLS_SECTION_TEMPLATE = """## 当前知识库（共 {count} 个技能，均为最新版）

{skills_content}
"""

OBSERVATION_MSG = """Observation（环境反馈）: {reason}

请根据上述观察补充遗漏的知识点，重新输出完整、结构化的回答。若技能文档确实未涵盖，请回答"技能文档未涵盖此知识点"。"""


def _tokenize(text: str) -> int:
    return len(ENC.encode(text))


class ReActCodingAgent:
    def __init__(self, skill_manager, evaluator, skill_optimizer=None,
                 max_react_rounds: int = 2, nudge_interval: int = 0,
                 model: str = "deepseek-chat"):
        self.skill_manager = skill_manager
        self.evaluator = evaluator          # 作为 ReAct 的"环境"，提供 Observation
        self.skill_optimizer = skill_optimizer  # 作为"自进化"能力，Nudge 时调用
        self.max_react_rounds = max_react_rounds
        self.nudge_interval = nudge_interval
        self.model = model
        self._iters_since_nudge = 0
        self.conversation_history: list[dict] = []   # 供进化 Agent 观察样本
        self.pending_failed_turns: list[dict] = []   # 本 Nudge 周期内累积的失败样本
        self.evolution_events: list[dict] = []       # 每次进化的记录

        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )

    # ── 对外接口 ──────────────────────────────────────────────────────────────

    def answer(self, task_text: str, task: dict) -> dict:
        """ReAct 循环回答单个任务。每次调用动态加载最新版 Skill。"""
        system_prompt = self._build_system_prompt()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"## 任务\n{task_text}\n\n请严格依据你的技能文档，给出完整、结构化的回答。"},
        ]

        prompt_tokens = completion_tokens = 0
        total_elapsed = 0.0
        answer_text = ""
        rounds = 0
        for i in range(self.max_react_rounds):
            t0 = time.time()
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                max_tokens=1200,
            )
            total_elapsed += time.time() - t0
            usage = resp.usage
            prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            answer_text = resp.choices[0].message.content.strip()
            rounds += 1
            messages.append({"role": "assistant", "content": answer_text})

            # Observation：环境（评估器）反馈
            ok, reason = self.evaluator.evaluate_answer(answer_text, task)
            if ok or i == self.max_react_rounds - 1:
                break
            messages.append({"role": "user", "content": OBSERVATION_MSG.format(reason=reason)})

        # 记录对话样本（供进化 Agent 观察失败原因），并推进 Nudge 计数
        self.conversation_history.append({
            "question": task_text, "title": task.get("title", ""),
            "answer": answer_text, "react_rounds": rounds,
            "skills_used": list(self.skill_manager.load_all().keys()),
        })
        if not ok:
            self.pending_failed_turns.append({
                "question": task_text, "title": task.get("title", ""),
                "answer": answer_text, "fail_reason": reason,
            })
        if len(self.conversation_history) > 50:
            self.conversation_history = self.conversation_history[-50:]

        result = {
            "answer": answer_text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "elapsed": round(total_elapsed, 3),
            "react_rounds": rounds,
        }

        # 自动迭代：达到 Nudge 间隔且有失败样本时进化 Skill
        self._iters_since_nudge += 1
        if self.should_trigger_nudge():
            self.evolve()

        return result

    def should_trigger_nudge(self) -> bool:
        if self.nudge_interval > 0 and self._iters_since_nudge >= self.nudge_interval:
            self._iters_since_nudge = 0
            return True
        return False

    def evolve(self) -> list[dict]:
        """自动迭代 Skill：
        - 有失败样本 → 进化 Agent 修复失败（fix 模式）
        - 零失败样本 → 进化 Agent 做 Token 压缩优化（compress 模式）
        无论哪种都让 Skill 迭代到新版本，skills/ 只保留最新版。"""
        failed_turns = self.pending_failed_turns
        self.pending_failed_turns = []
        if not self.skill_optimizer:
            self.evolution_events.append({"triggered": True, "actions": [], "skipped": True})
            return []
        actions = self.skill_optimizer.optimize(failed_turns, self.skill_manager)
        self.evolution_events.append({
            "triggered": True,
            "mode": "fix" if failed_turns else "refine",
            "actions": actions,
        })
        return actions

    # ── 内部 ──────────────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        skills = self.skill_manager.load_all()   # 永远读 skills/ 下的最新版
        if not skills:
            skills_section = "（暂无技能文档，所有任务均回答：技能文档未涵盖此知识点）"
        else:
            parts = [f"### 技能：{name}\n{content}" for name, content in sorted(skills.items())]
            skills_section = SKILLS_SECTION_TEMPLATE.format(
                count=len(skills), skills_content="\n\n---\n\n".join(parts))
        return SYSTEM_TEMPLATE.format(
            max_react_rounds=self.max_react_rounds, skills_section=skills_section)
