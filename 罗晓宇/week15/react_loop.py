'''
通用 ReAct 循环引擎

CLI使用，不需要保存记录节点

'''

import time, re, json, logging
from typing import Optional
from llm_client import llm_chat

logger = logging.getLogger(__name__)


REACT_SYSTEM = """你是旅游攻略助手，能用以下工具联网搜索调研。

可用工具：
{tools_desc}

按如下格式严格输出（每轮一次 Thought/Action/Action Input）：
Thought: 你的推理，分析还需查什么
Action: 工具名
Action Input: 工具参数（list）

工具执行后会得到 Observation。多轮调用直到能给出完整答案，最后用：
Thought: 我已收集足够信息
Final Answer: 综合答案（带来源要点）

规则：
- Action 必须是上面列出的工具名之一
- Action Input 是该工具的参数字符串
- 每轮只调一次工具，等 Observation 再决定下一步"""

def build_tools_desc(tools: list) -> str:
    """把工具列表格式化成 ReAct 系统提示的可读描述。"""
    lines = []
    for name, (fn, desc) in tools.items():
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)



class ReActLoop:
    """通用 ReAct 循环引擎。主agent /subagent都可用。"""

    def __init__(self, agent_name: str, tools: dict,
                 max_steps: int = 6, model_tag: str = "deepseek-chat",
                 system_prompt: Optional[str] = None):
        """
        tools: {tool_name: (fn(arg)->str, description_str)}
        system_prompt: 自定义系统提示（主 agent 用 MAIN_SYSTEM 引导派发）。
                       None 时用默认 REACT_SYSTEM。{tools_desc} 占位符会被替换。
        """
        self.agent_name = agent_name
        self.tools = tools          # {name: (fn, desc)}
        self.max_steps = max_steps
        self.model_tag = model_tag
        self._system_template = system_prompt or REACT_SYSTEM
        self.trace: list[dict] = []  # 本轮执行 trace（点节点查看用）

    def run(self, question: str, 
            shared_state: dict = None) -> dict:
        """
        执行 ReAct 循环。
        shared_state: 共享状态 dict（主 agent 派发 subagent 时往里塞 subagent trace）。
        返回 {final_answer, trace, duration}。
        """
        self.trace = []
        t0 = time.time()
        system = self._system_template.format(tools_desc=build_tools_desc(self.tools))
        # 对话历史：累积 Thought/Action/ActionInput/Observation
        history = f"Question: {question}\n\n"
        final_answer = ""

        for step_idx in range(self.max_steps):
            llm_out = llm_chat(system, history, temperature=0.0,
                               max_tokens=4096, stop=["Observation:"])

            # 解析Action 或 Final Answer
            thought, action, action_input = self._parse(llm_out)

            step = {"idx": step_idx, "agent": self.agent_name,
                    "thought": thought, "action": action,
                    "action_input": action_input, "observation": None}

            if action == "Final Answer":
                step["final"] = True
                final_answer = action_input
                self.trace.append(step)
                self._print_trace(step)
                break


            # 执行工具（可能很慢，如 dispatch_subagents 要等所有子 agent 跑完）
            observation = self._exec_tool(action, action_input, shared_state)

            # ── post 执行：同一 idx 再发一次，带真实 observation ──
            step["observation"] = observation
            step["done"] = True
            self.trace.append(step)
            self._print_trace(step)

            # 续写历史
            history += llm_out + f"Observation: {observation}\n"

        else:
            # 超过 max_steps，强制收尾
            final_answer = "（已达最大步数）" + (self.trace[-1].get("observation","") or "")
            step = {"idx": self.max_steps, "agent": self.agent_name,
                    "thought": "达到步数上限", "action": "Final Answer",
                    "action_input": final_answer, "observation": None, "final": True}
            self.trace.append(step)
            self._print_trace(step)

        duration = round(time.time() - t0, 2)
        return {"final_answer": final_answer, "trace": self.trace,
                "duration": duration}


    def _print_trace(self, current_step: dict):
        """一次性整齐打印整个 trace 节点（不在外面提前取局部变量）。"""
        print("\n" + "-"*50 + "TRACE" + "-"*50)
        print(f"[{current_step.get('agent','')}] Step {current_step.get('idx','')}{' (FINAL)' if current_step.get('final') else ''}")
        print("Thought:", end=" ")
        print(current_step.get('thought',''))
        print("Action:", end=" ")
        print(current_step.get('action',''))
        print("Action Input:", end=" ")
        print(current_step.get('action_input', '')[:100])
        
        print("Observation:")
        obs = current_step.get('observation')
        print((obs or '')[:100])
        print("Status:")
        print("done" if current_step.get('done') else "pending")
        print("-"*100 + "\n")


    def _parse(self, text: str) -> tuple[str, str, object]:
        """从 LLM 输出解析 Thought/Action/Action Input。
        返回 (thought, action, action_input)。Final Answer 时 action='Final Answer'。
        action_input 会尽量解析为 Python 列表（支持 JSON 列表或用换行/逗号分隔的多参数）。
        兜底：若没匹配到 Action 也没 Final Answer，但有实质文本，当作 Final Answer
        （LLM 拿到子搜索结果后常直接写报告、不带 Final Answer 前缀）。"""
        thought = ""
        m = re.search(r"Thought:\s*(.*?)(?=\nAction:|$)", text, re.S)
        if m: thought = m.group(1).strip()[:500]

        # Final Answer 优先检测
        mfa = re.search(r"Final Answer:\s*(.*)", text, re.S)
        if mfa:
            return thought, "Final Answer", mfa.group(1).strip()

        # Action / Action Input
        ma = re.search(r"Action:\s*(.*)", text)
        mi = re.search(r"Action Input:\s*(.*)", text, re.S)
        if ma:
            action = ma.group(1).strip()
            raw = (mi.group(1).strip() if mi else "")
            action_input = []
            if raw:
                # 优先尝试解析为 JSON（允许传入 JSON 列表/对象）
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        action_input = parsed
                    else:
                        action_input = [parsed]
                except Exception:
                    # 回退：按换行或逗号分割为多个参数
                    parts = [p.strip() for p in re.split(r"[\n,]+", raw) if p.strip()]
                    action_input = parts
            return thought, action, action_input

        # 兜底：有实质文本但无格式标记 → 当作 Final Answer
        if text.strip():
            return thought or "综合搜索结果给出攻略", "Final Answer", text.strip()
        return thought, "", ""

    def _exec_tool(self, action: str, action_input: object, shared_state: dict) -> str:
        """执行工具，返回 observation 文本。未知工具返回错误说明。
        若 action_input 是列表，则按位置参数解包调用工具函数：`fn(*action_input, ...)`。
        否则按单一参数调用：`fn(action_input)`。
        保留对 shared_state 的可选传递。"""
        if action not in self.tools:
            return f"工具 '{action}' 不存在，可选: {list(self.tools.keys())}"
        fn, _ = self.tools[action]
        try:
            # 如果解析出的 action_input 是列表，解包为位置参数调用工具
            if isinstance(action_input, list):
                if shared_state is not None:
                    return str(fn(*action_input, shared_state=shared_state))
                else:
                    return str(fn(*action_input))
            else:
                # 单一参数调用（保持向后兼容）
                if shared_state is not None:
                    return str(fn(action_input, shared_state=shared_state))
                else:
                    return str(fn(action_input))
        except Exception as e:
            return f"工具执行出错: {type(e).__name__}: {str(e)[:120]}"