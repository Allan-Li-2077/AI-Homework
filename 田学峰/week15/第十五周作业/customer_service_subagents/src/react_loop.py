"""通用 ReAct 循环引擎（智能客服版）

教学重点：
  1. ReAct = Reason + Act：LLM 输出 Thought → Action → Action Input，
     runner 执行工具得 Observation，再喂回 LLM 续写，直到 Final Answer
  2. 主客服 agent 和子客服 agent 都是 ReAct 循环——区别只在工具集
  3. 完整 trace 捕获每步，供可视化「点节点看 ReAct 过程」用

用 stop=["Observation:"] 让 LLM 在 Action Input 后停下，runner 执行工具
再补 Observation 续写——ReAct 经典实现技巧。
"""
import time, re, logging
from typing import Callable, Optional
from llm_client import llm_chat

logger = logging.getLogger(__name__)

REACT_SYSTEM = """你是智能客服助手，能用以下工具为客户解决问题。

可用工具：
{tools_desc}

按如下格式严格输出（每轮一次 Thought/Action/Action Input）：
Thought: 分析客户问题、判断需要查什么
Action: 工具名
Action Input: 工具参数（字符串）

工具执行后会得到 Observation。多轮调用直到能给出完整答复，最后用：
Thought: 我已收集足够信息
Final Answer: 给客户的答复（清晰、礼貌、分点）

规则：
- Action 必须是上面列出的工具名之一
- Action Input 是该工具的参数字符串
- 每轮只调一次工具，等 Observation 再决定下一步
- 答复要礼貌专业，必要时分点说明"""


def build_tools_desc(tools: dict) -> str:
    """把 tools 字典格式化成工具说明。tools: {name: (fn, description)}"""
    lines = []
    for name, (fn, desc) in tools.items():
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)


class ReActLoop:
    """通用 ReAct 循环。主客服 / 子客服 各自实例化一个。"""

    def __init__(self, agent_name: str, tools: dict,
                 max_steps: int = 6, model_tag: str = "deepseek-chat",
                 system_prompt: Optional[str] = None,
                 role_desc: str = "客服"):
        """
        tools: {tool_name: (fn(arg)->str, description_str)}
        system_prompt: 自定义系统提示（主 agent 用 MAIN_SYSTEM 引导派发）。
                       None 时用默认 REACT_SYSTEM。{tools_desc} 占位符会被替换。
        role_desc: subagent 专长描述（如"订单专员"），写进 prompt 增强专业性。
        """
        self.agent_name = agent_name
        self.tools = tools
        self.max_steps = max_steps
        self.model_tag = model_tag
        self._system_template = system_prompt or REACT_SYSTEM
        self.role_desc = role_desc
        self.trace: list[dict] = []

    def run(self, question: str, on_step: Callable = None,
            shared_state: dict = None) -> dict:
        """
        执行 ReAct 循环。
        on_step(step_dict): 每步回调（SSE 流式用）。
        shared_state: 共享状态 dict（主 agent 派发 subagent 时往里塞 trace）。
        返回 {final_answer, trace, duration}。
        """
        self.trace = []
        t0 = time.time()
        system = self._system_template.format(
            tools_desc=build_tools_desc(self.tools)
        ).replace("{role}", self.role_desc)
        history = f"客户问题: {question}\n\n"
        final_answer = ""

        for step_idx in range(self.max_steps):
            llm_out = llm_chat(system, history, temperature=0.0,
                               max_tokens=768, stop=["Observation:"])
            thought, action, action_input = self._parse(llm_out)

            step = {"idx": step_idx, "agent": self.agent_name,
                    "thought": thought, "action": action,
                    "action_input": action_input, "observation": None}

            if action == "Final Answer":
                step["final"] = True
                final_answer = action_input
                self.trace.append(step)
                if on_step: on_step(step)
                break

            step["final"] = False
            if on_step: on_step(step)

            observation = self._exec_tool(action, action_input, shared_state)

            step["observation"] = observation
            step["done"] = True
            self.trace.append(step)
            if on_step: on_step(step)

            history += llm_out + f"Observation: {observation[:1200]}\n"
        else:
            final_answer = "（已达最大步数）" + (self.trace[-1].get("observation", "") or "")
            step = {"idx": self.max_steps, "agent": self.agent_name,
                    "thought": "达到步数上限", "action": "Final Answer",
                    "action_input": final_answer, "observation": None, "final": True}
            self.trace.append(step)
            if on_step: on_step(step)

        duration = round(time.time() - t0, 2)
        return {"final_answer": final_answer, "trace": self.trace,
                "duration": duration}

    def _parse(self, text: str) -> tuple[str, str, str]:
        """从 LLM 输出解析 Thought/Action/Action Input。
        返回 (thought, action, action_input)。Final Answer 时 action='Final Answer'。
        兜底：没匹配到 Action 也没 Final Answer 但有实质文本 → 当 Final Answer。"""
        thought = ""
        m = re.search(r"Thought:\s*(.*?)(?=\nAction:|$)", text, re.S)
        if m: thought = m.group(1).strip()[:400]

        mfa = re.search(r"Final Answer:\s*(.*)", text, re.S)
        if mfa:
            return thought, "Final Answer", mfa.group(1).strip()

        ma = re.search(r"Action:\s*(.*)", text)
        mi = re.search(r"Action Input:\s*(.*)", text)
        if ma:
            action = ma.group(1).strip()
            action_input = (mi.group(1).strip() if mi else "")
            return thought, action, action_input

        if text.strip():
            return thought or "综合处理后给出答复", "Final Answer", text.strip()
        return thought, "", ""

    def _exec_tool(self, action: str, action_input: str, shared_state: dict) -> str:
        """执行工具，返回 observation 文本。未知工具返回错误说明。"""
        if action not in self.tools:
            return f"工具 '{action}' 不存在，可选: {list(self.tools.keys())}"
        fn, _ = self.tools[action]
        try:
            return str(fn(action_input, shared_state=shared_state)
                       if shared_state is not None else fn(action_input))
        except Exception as e:
            return f"工具执行出错: {type(e).__name__}: {str(e)[:120]}"


if __name__ == "__main__":
    import logging as _l
    _l.basicConfig(level=_l.WARNING)
    from customer_tools import query_order, query_faq

    loop = ReActLoop("test",
                     tools={"query_order": (query_order, "查询订单，参数=订单号"),
                            "query_faq": (query_faq, "查询政策，参数=关键词")},
                     max_steps=4)
    r = loop.run("帮我查一下订单 A100002 到哪了，还有退货政策是什么？")
    print(f"\n答复: {r['final_answer'][:200]}")
    print(f"trace {len(r['trace'])} 步")
    for s in r["trace"]:
        print(f"  [{s['idx']}] {s['action']}({s['action_input'][:40]}) → {(s.get('observation') or '')[:50]}")
