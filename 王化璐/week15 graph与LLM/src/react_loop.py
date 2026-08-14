"""
求职公司调研 - 通用 ReAct 循环引擎
严格仿照 market_research_subagents：Thought→Action→Action Input→Observation→循环
主 agent 和 subagent 共用这个类，区别只在 tools 字典。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

from . import llm_client


@dataclass
class StepEvent:
    """ReAct 每一步的事件记录：用于 SSE 推送 / CLI 打印 / 测试追踪"""
    role: str                       # "main" 或 "sub_xxx"
    step_index: int
    thought: str = ""
    action: str = ""
    action_input: str = ""
    observation: str = ""
    final_answer: str = ""
    elapsed_ms: int = 0


@dataclass
class ReActResult:
    final_answer: str
    steps: list[StepEvent] = field(default_factory=list)
    total_ms: int = 0


# 解析 ReAct 输出的正则——和原项目完全一致
_RE_THOUGHT = re.compile(r"Thought:(.+?)(?=Action:|Final Answer:|$)", re.S)
_RE_ACTION = re.compile(r"Action:\s*([A-Za-z0-9_]+)")
_RE_ACTION_INPUT = re.compile(r"Action Input:(.+?)(?=Observation:|$)", re.S)
_RE_FINAL = re.compile(r"Final Answer:(.+)$", re.S)


def _parse_react_output(text: str) -> dict:
    """从 LLM 一段输出里抽取 thought/action/input/final_answer 字段"""
    out = {"thought": "", "action": "", "action_input": "", "final_answer": ""}
    m = _RE_THOUGHT.search(text)
    if m:
        out["thought"] = m.group(1).strip()
    m = _RE_ACTION.search(text)
    if m:
        out["action"] = m.group(1).strip()
    m = _RE_ACTION_INPUT.search(text)
    if m:
        out["action_input"] = m.group(1).strip()
    m = _RE_FINAL.search(text)
    if m:
        out["final_answer"] = m.group(1).strip()
    return out


class ReActLoop:
    """
    通用 ReAct 循环。
    - system:  系统提示词（主 agent / subagent 不同）
    - tools:   {"tool_name": fn(input_str)->str}，工具的输入输出都是字符串
    - role:    事件标记用，例如 "main" / "sub_market_size"
    - max_steps: 最大步数，防止死循环
    - event_cb: 每走一步回调一次 StepEvent，用于 SSE 推送
    """

    def __init__(self, system: str, tools: dict[str, Callable[[str], str]],
                 role: str = "main", max_steps: int = 10,
                 event_cb: Callable[[StepEvent], None] | None = None):
        self.system = system
        self.tools = tools
        self.role = role
        self.max_steps = max_steps
        self.event_cb = event_cb

    def run(self, question: str) -> ReActResult:
        t0 = time.perf_counter()
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": f"Question: {question}"},
        ]
        steps: list[StepEvent] = []
        final_answer = ""

        for idx in range(1, self.max_steps + 1):
            t_step = time.perf_counter()
            raw = llm_client.chat(messages, temperature=0.2, stop=["Observation:"], max_tokens=2048)
            assistant_msg_content = raw
            parsed = _parse_react_output(assistant_msg_content)

            evt = StepEvent(
                role=self.role,
                step_index=idx,
                thought=parsed["thought"],
                action=parsed["action"],
                action_input=parsed["action_input"],
                final_answer=parsed["final_answer"],
            )

            if parsed["final_answer"] and not parsed["action"]:
                # 到终点了
                final_answer = parsed["final_answer"].strip()
                evt.elapsed_ms = int((time.perf_counter() - t_step) * 1000)
                steps.append(evt)
                if self.event_cb:
                    self.event_cb(evt)
                break

            # 调工具
            tool_name = parsed["action"]
            tool_input = parsed["action_input"]
            obs_text = ""
            if not tool_name:
                obs_text = "[解析错误：LLM 没输出 Action，请按 ReAct 格式重写]"
            elif tool_name not in self.tools:
                obs_text = f"[错误：未知工具 '{tool_name}'。可用工具: {list(self.tools.keys())}]"
            else:
                try:
                    obs_text = str(self.tools[tool_name](tool_input))
                except Exception as e:
                    obs_text = f"[工具执行异常] {type(e).__name__}: {e}"

            # Observation 截断，避免上下文爆炸
            if len(obs_text) > 3000:
                obs_text = obs_text[:3000] + "\n...[内容过长已截断]"

            evt.observation = obs_text
            evt.elapsed_ms = int((time.perf_counter() - t_step) * 1000)
            steps.append(evt)
            if self.event_cb:
                self.event_cb(evt)

            # 把 LLM 回复 + Observation 塞进上下文
            messages.append({"role": "assistant", "content": assistant_msg_content})
            messages.append({"role": "user", "content": f"Observation: {obs_text}\n如果已经有足够信息就输出 Final Answer，否则继续 Thought/Action。"})
        else:
            # 超过最大步数
            final_answer = f"[已达最大步数 {self.max_steps}，以下是最后一步可用信息汇总]\n\n"
            for s in steps[-3:]:
                if s.observation:
                    final_answer += f"- 步骤{s.step_index} Observation: {s.observation[:500]}\n"

        total_ms = int((time.perf_counter() - t0) * 1000)
        return ReActResult(final_answer=final_answer, steps=steps, total_ms=total_ms)
