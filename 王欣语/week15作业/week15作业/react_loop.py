"""
通用 ReAct 循环引擎

教学重点：
  1. ReAct = Reason + Act：LLM 生成 Thought(推理) → Action(选工具) → Action Input(参数)，
     runner 执行工具得 Observation，再喂回 LLM 继续，直到 Final Answer
  2. 主 agent 和 subagent 都是 ReAct 循环——区别只在「有哪些工具」：
     主 agent 有 web_search + dispatch_subagents，subagent 只有 web_search
  3. 完整 trace 捕获：每步 Thought/Action/ActionInput/Observation 存下来

用 stop=["Observation:"] 让 LLM 在生成完 Action Input 后停下，runner 执行工具
再补 Observation 续写——这是 ReAct 的经典实现技巧。
"""

import time
import re
import logging
from typing import Callable, Optional

from llm_client import llm_chat

logger = logging.getLogger(__name__)

# 默认系统提示（subagent 用）
REACT_SYSTEM = """你是调研助手，能用以下工具联网搜索调研。

可用工具：
{tools_desc}

按如下格式严格输出（每轮一次 Thought/Action/Action Input）：
Thought: 你的推理，分析还需查什么
Action: 工具名
Action Input: 工具参数（字符串）

工具执行后会得到 Observation。多轮调用直到能给出完整答案，最后用：
Thought: 我已收集足够信息
Final Answer: 综合答案（带来源要点）

规则：
- Action 必须是上面列出的工具名之一
- Action Input 是该工具的参数字符串
- 每轮只调一次工具，等 Observation 再决定下一步"""


def build_tools_desc(tools: dict) -> str:
    """把 tools 字典格式化成工具说明。tools: {name: (fn, description)}"""
    lines = []
    for name, (fn, desc) in tools.items():
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)


class ReActLoop:
    """通用 ReAct 循环。主 agent / subagent 各自实例化一个。"""

    def __init__(self, agent_name: str, tools: dict,
                 max_steps: int = 6, model_tag: str = "deepseek-chat",
                 system_prompt: Optional[str] = None):
        """
        Args:
            agent_name: agent 标识名
            tools: {tool_name: (fn(arg)->str, description_str)}
            max_steps: 最大步数
            model_tag: 模型标识（用于日志）
            system_prompt: 自定义系统提示（主 agent 用 MAIN_SYSTEM 引导派发）
        """
        self.agent_name = agent_name
        self.tools = tools
        self.max_steps = max_steps
        self.model_tag = model_tag
        self._system_template = system_prompt or REACT_SYSTEM
        self.trace: list[dict] = []

    def run(self, question: str, on_step: Callable = None,
            shared_state: dict = None) -> dict:
        """
        执行 ReAct 循环
        
        Args:
            question: 用户问题
            on_step: 每步回调函数
            shared_state: 共享状态 dict
        
        Returns:
            {"final_answer": str, "trace": list, "duration": float}
        """
        self.trace = []
        t0 = time.time()
        
        # 构建系统提示（替换 tools_desc 占位符）
        system = self._system_template.format(tools_desc=build_tools_desc(self.tools))
        
        # 对话历史
        history = f"Question: {question}\n\n"
        final_answer = ""

        for step_idx in range(self.max_steps):
            # 调 LLM 生成下一步（停在 Observation: 前）
            llm_out = llm_chat(system, history, temperature=0.0,
                               max_tokens=768, stop=["Observation:"])
            
            # 解析 Action 或 Final Answer
            thought, action, action_input = self._parse(llm_out)

            step = {
                "idx": step_idx,
                "agent": self.agent_name,
                "thought": thought,
                "action": action,
                "action_input": action_input,
                "observation": None
            }

            if action == "Final Answer":
                step["final"] = True
                final_answer = action_input
                self.trace.append(step)
                if on_step:
                    on_step(step)
                break

            # 执行前回调（让前端马上看到决策）
            step["final"] = False
            if on_step:
                on_step(step)

            # 执行工具
            observation = self._exec_tool(action, action_input, shared_state)

            # 执行后回调（带真实 observation）
            step["observation"] = observation
            step["done"] = True
            self.trace.append(step)
            if on_step:
                on_step(step)

            # 续写历史
            history += llm_out + f"Observation: {observation[:1200]}\n"

        else:
            # 超过 max_steps，强制收尾
            final_answer = "（已达最大步数）" + (self.trace[-1].get("observation", "") or "")
            step = {
                "idx": self.max_steps,
                "agent": self.agent_name,
                "thought": "达到步数上限",
                "action": "Final Answer",
                "action_input": final_answer,
                "observation": None,
                "final": True
            }
            self.trace.append(step)
            if on_step:
                on_step(step)

        duration = round(time.time() - t0, 2)
        return {
            "final_answer": final_answer,
            "trace": self.trace,
            "duration": duration
        }

    def _parse(self, text: str) -> tuple[str, str, str]:
        """
        从 LLM 输出解析 Thought/Action/Action Input
        
        返回: (thought, action, action_input)
        Final Answer 时 action='Final Answer'
        
        兜底：若没匹配到 Action 也没 Final Answer，但有实质文本，当作 Final Answer
        """
        thought = ""
        m = re.search(r"Thought:\s*(.*?)(?=\nAction:|$)", text, re.S)
        if m:
            thought = m.group(1).strip()[:400]

        # Final Answer 优先检测
        mfa = re.search(r"Final Answer:\s*(.*)", text, re.S)
        if mfa:
            return thought, "Final Answer", mfa.group(1).strip()

        # Action / Action Input
        ma = re.search(r"Action:\s*(.*)", text)
        mi = re.search(r"Action Input:\s*(.*)", text)
        if ma:
            action = ma.group(1).strip()
            action_input = (mi.group(1).strip() if mi else "")
            return thought, action, action_input

        # 兜底：有实质文本但无格式标记 → 当作 Final Answer
        if text.strip():
            return thought or "综合调研结果给出报告", "Final Answer", text.strip()
        
        return thought, "", ""

    def _exec_tool(self, action: str, action_input: str, shared_state: dict) -> str:
        """执行工具，返回 observation 文本"""
        if action not in self.tools:
            return f"工具 '{action}' 不存在，可选: {list(self.tools.keys())}"
        
        fn, _ = self.tools[action]
        try:
            # 工具可能需要 shared_state（dispatch_subagents 用）
            if shared_state is not None:
                return str(fn(action_input, shared_state=shared_state))
            else:
                return str(fn(action_input))
        except Exception as e:
            return f"工具执行出错: {type(e).__name__}: {str(e)[:120]}"
