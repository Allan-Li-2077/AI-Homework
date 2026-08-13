"""
ReAct 循环引擎 - 同步版本（在线程中直接运行，不依赖 asyncio 嵌套）
"""
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .llm_client import llm_chat_sync


@dataclass
class ReActStep:
    """ReAct 单步记录"""
    step_num: int
    thought: str
    action: str
    action_input: str
    observation: str = ""


@dataclass
class ReActResult:
    """ReAct 执行结果"""
    final_answer: str
    steps: list[ReActStep]
    total_steps: int
    wall_clock: float


class ReActLoop:
    """
    通用 ReAct 循环引擎（同步版，供线程内直接调用）
    """

    def __init__(
        self,
        agent_name: str,
        tools: dict,
        max_steps: int = 15,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ):
        self.agent_name = agent_name
        self.tools = tools
        self.max_steps = max_steps
        self.temperature = temperature
        self._system = system_prompt or ""

    def _build_tools_desc(self) -> str:
        return "\n".join(
            f"- {name}: {desc}" for name, (_, desc) in self.tools.items()
        )

    def _build_prompt(self, query: str, history: str = "") -> str:
        return (
            f"{self._system}\n\n"
            f"历史步骤:\n{history}\n\n"
            f"当前问题: {query}\n\n"
            f"请按以下格式输出:\n"
            f"Thought: 你思考要做什么\n"
            f"Action: 工具名（直接回答写 final_answer）\n"
            f"Action Input: 工具参数或你的完整回答\n"
        )

    def _parse(self, text: str) -> tuple[str, str, str]:
        """解析 LLM 输出。返回 (thought, action, action_input)"""
        thought_m = re.search(r"Thought:\s*(.*?)(?=\nAction:|\Z)", text, re.DOTALL)
        thought = thought_m.group(1).strip() if thought_m else ""

        fa_m = re.search(r"Final Answer:\s*(.*)", text, re.DOTALL)
        if fa_m:
            return thought, "final_answer", fa_m.group(1).strip()

        action_m = re.search(r"Action:\s*(\w+)", text)
        action = action_m.group(1).strip() if action_m else ""
        action_input_m = re.search(r"Action Input:\s*(.*)", text, re.DOTALL)
        action_input = action_input_m.group(1).strip() if action_input_m else ""

        if not action and text.strip():
            return thought, "final_answer", text.strip()
        return thought, action, action_input

    def _exec_tool(self, action: str, action_input: str, shared_state: dict) -> str:
        """执行工具，返回 observation"""
        if action not in self.tools:
            return f"未知工具: {action}，可选: {list(self.tools.keys())}"
        fn, _ = self.tools[action]
        try:
            return str(fn(action_input, shared_state=shared_state)
                       if shared_state is not None else fn(action_input))
        except Exception as e:
            return f"工具执行错误: {type(e).__name__}: {str(e)[:120]}"

    def run(self, query: str, on_step: Optional[Callable] = None,
            shared_state: dict = None) -> ReActResult:
        """
        同步执行 ReAct 循环。
        on_step: 每步完成的回调，签名 step_dict -> None
        """
        start_time = time.time()
        steps: list[ReActStep] = []
        history = ""
        current_query = query
        final_answer = ""

        for step_num in range(1, self.max_steps + 1):
            prompt = self._build_prompt(current_query, history)

            # 同步 LLM 调用
            llm_response = llm_chat_sync(
                system=prompt,
                user="请按格式输出",
                temperature=self.temperature,
                max_tokens=512,
                stop=["Observation:"],
            )

            thought, action, action_input = self._parse(llm_response)
            is_final = (action == "final_answer")

            step = ReActStep(
                step_num=step_num,
                thought=thought,
                action=action,
                action_input=action_input,
                observation="",
            )

            if is_final:
                step.observation = "完成"
                steps.append(step)
                final_answer = action_input
                if on_step:
                    on_step({
                        "step_num": step_num,
                        "thought": thought,
                        "action": action,
                        "action_input": action_input,
                        "observation": "完成",
                        "final": True,
                    })
                break

            # pre 回调（无 observation，先让前端看到决策）
            if on_step:
                on_step({
                    "step_num": step_num,
                    "thought": thought,
                    "action": action,
                    "action_input": action_input,
                    "observation": None,
                    "final": False,
                })

            # 执行工具
            observation = self._exec_tool(action, action_input, shared_state)
            step.observation = observation

            # post 回调（带 observation）
            if on_step:
                on_step({
                    "step_num": step_num,
                    "thought": thought,
                    "action": action,
                    "action_input": action_input,
                    "observation": observation,
                    "final": False,
                })

            steps.append(step)
            history += (
                f"\nThought: {thought}\n"
                f"Action: {action}\n"
                f"Action Input: {action_input}\n"
                f"Observation: {observation[:500]}\n"
            )
            current_query = f"上一步结果是: {observation[:500]}\n请基于此继续或完成回答。"
        else:
            final_answer = f"达到最大步数限制 ({self.max_steps})"

        return ReActResult(
            final_answer=final_answer,
            steps=steps,
            total_steps=len(steps),
            wall_clock=time.time() - start_time,
        )
