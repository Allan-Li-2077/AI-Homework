"""通用 ReAct 循环引擎（JSON 结构化输出版）

教学重点：
  1. ReAct = Reason + Act：LLM 每轮输出一个 JSON（thought/action/action_input 或 final_answer），
     runner 执行工具得 Observation，再喂回 LLM 继续，直到 final_answer
  2. 主 agent 和子 agent 都是这个类——区别只在「有哪些工具」
  3. 完整 trace 捕获：每步 thought/action/action_input/observation 存下来，
     供 CLI 打印 ReAct 过程

依赖：llm_client（json_mode）+ 工具函数
"""

import time
import re
import json
import logging
from typing import Callable, Optional
from llm_client import llm_chat



REACT_SYSTEM = """可用工具：
{tools_desc}

每轮只输出一个 JSON（json 格式）：
- 调工具：{{"thought": "...", "action": "工具名", "action_input": "参数"}}
- 给答案：{{"thought": "...", "final_answer": "答案"}}
action 必须是工具名；会被 json.loads 解析，勿加多余文字"""

def build_tools_desc(tools: dict) -> str:
    """把 tools 字典格式化成工具说明。tools: {name: (fn, description)}"""
    lines = [f"- {name}: {desc}" for name, (fn, desc) in tools.items()]
    return "\n".join(lines)

class ReActLoop:
    """通用 ReAct 循环。主 agent / subagent 各自实例化一个。"""

    def __init__(self, agent_name: str, tools: dict,
                max_steps: int = 6, model_tag: str = "deepseek-chat",
                system_prompt: Optional[str] = None):
        """
        tools: {tool_name: (fn(arg)->str, description_str)}
        system_prompt: 角色/主 agent 前缀提示（身份+规范），拼接在通用 REACT_SYSTEM
                       骨架之前。None 时只用通用骨架。
        """
        self.agent_name = agent_name
        self.tools = tools
        self.max_steps = max_steps
        self.model_tag = model_tag
        self._system_prefix = system_prompt
        self.trace: list[dict] = []

    def run(self, question: str, on_step: Callable = None,
            shared_state: dict = None) -> dict:
        """
        执行 ReAct 循环。
        on_step(step_dict): 每步回调（CLI 打印用）。
        shared_state: 共享状态 dict（主 agent 派发 subagent 时往里塞 subagent trace）。
        返回 {final_answer, trace, duration}。
        """
        self.trace = []
        t0 = time.time()
        # 拼接：角色前缀 + 通用骨架（协议只写一份，各角色/主 agent 复用）
        base_system = REACT_SYSTEM.format(tools_desc=build_tools_desc(self.tools))
        system = (self._system_prefix + "\n\n" + base_system
                  if self._system_prefix else base_system)
        # 对话历史：Question + 每轮的 JSON 输出 + Observation
        history = f"Question: {question}\n\n"
        final_answer = ""

        for step_idx in range(self.max_steps):
            # ── 关键：json_mode=True 在这里生效（串起 llm_client）──
            llm_out = llm_chat(system, history, temperature=0.0,
                               max_tokens=1024, json_mode=True)
            thought, action, action_input = self._parse(llm_out)

            step = {"idx": step_idx, "agent": self.agent_name,
                    "thought": thought, "action": action,
                    "action_input": action_input, "observation": None}

            if action == "Final Answer":
                step["final"] = True
                final_answer = action_input
                self.trace.append(step)
                if on_step: on_step(step)      # final：单次回调
                break

            # pre 回调：工具执行前先广播决策（CLI 实时显示"正在搜索…"）
            step["final"] = False
            if on_step: on_step(step)

            observation = self._exec_tool(action, action_input, shared_state)

            # post 回调：同一 idx 带真实 observation 再发一次
            step["observation"] = observation
            step["done"] = True
            self.trace.append(step)
            if on_step: on_step(step)

            # 历史拼接：JSON 输出直接拼（没有模型自猜 Observation 的污染问题）
            history += llm_out + f"\nObservation: {observation[:800]}\n"

        else:
            # 超过 max_steps 强制收尾
            final_answer = "（已达最大步数）" + (self.trace[-1].get("observation", "") or "")
            step = {"idx": self.max_steps, "agent": self.agent_name,
                    "thought": "达到步数上限", "action": "Final Answer",
                    "action_input": final_answer, "observation": None, "final": True}
            self.trace.append(step)
            if on_step: on_step(step)

        duration = round(time.time() - t0, 2)
        return {"final_answer": final_answer, "trace": self.trace, "duration": duration}
        
    def _parse(self, text: str) -> tuple[str, str, str]:
        """从 LLM 输出解析 JSON 格式的 ReAct 步骤。
        返回 (thought, action, action_input)。final_answer 时 action='Final Answer'。
        兜底链：JSON 解析 → 正则 → 有文本当 Final Answer"""
        thought = ""
        try:
            # ① 剥掉模型可能包的 ```json 代码块标记
            clean = re.sub(r"```(?:json)?|```", "", text).strip()
            # ② 取第一个 { 到最后一个 } 之间的内容
            start, end = clean.find("{"), clean.rfind("}")
            data = json.loads(clean[start:end + 1])
            thought = str(data.get("thought", ""))
            if "final_answer" in data:
                return thought, "Final Answer", str(data["final_answer"])
            return thought, str(data.get("action", "")), str(data.get("action_input", ""))
        except Exception:
            pass  # JSON 解析失败，走兜底

        # ② 兜底：正则（模型偶尔输出纯文本格式）
        m = re.search(r"Thought:\s*(.*?)(?=\nAction:|$)", text, re.S)
        if m: thought = m.group(1).strip()[:400]
        mfa = re.search(r"Final Answer:\s*(.*)", text, re.S)
        if mfa: return thought, "Final Answer", mfa.group(1).strip()
        ma = re.search(r"Action:\s*(.*)", text)
        mi = re.search(r"Action Input:\s*(.*)", text)
        if ma:
            return thought, ma.group(1).strip(), (mi.group(1).strip() if mi else "")
        # ③ 终极兜底：有实质文本 → 当 Final Answer（避免空 action 死循环）
        if text.strip():
            return thought or "综合调研结果给出报告", "Final Answer", text.strip()
        return thought, "", ""

    def _exec_tool(self, action: str, action_input: str, shared_state: dict) -> str:
        """执行工具，返回 observation 文本。未知工具返回错误说明。"""
        if action not in self.tools:
            return f"工具 '{action}' 不存在，可选: {list(self.tools.keys())}"
        fn, _ = self.tools[action]
        try:
            # 工具可能需要 shared_state（dispatch_subagents 用）
            return str(fn(action_input, shared_state=shared_state)
                       if shared_state is not None else fn(action_input))
        except Exception as e:
            return f"工具执行出错: {type(e).__name__}: {str(e)[:120]}"
