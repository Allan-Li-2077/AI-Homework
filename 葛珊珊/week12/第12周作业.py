"""
手写 Prompt 解析版 ReAct Agent

教学重点：
  1. ReAct 核心循环：Thought → Action → Observation，逐步推理
  2. System Prompt 约束输出格式，Python 正则解析每一步
  3. 对话历史拼接方式：每轮结果追加到 prompt，形成上下文记忆
  4. 停止条件：模型输出 Final Answer 或达到最大步数

使用方式：
  python react_manual.py
  python react_manual.py --question "茅台和五粮液2023年毛利率差多少？"
  python react_manual.py --question "..." --max_steps 8 --verbose

依赖：
  pip install openai faiss-cpu sentence-transformers akshare
  export DASHSCOPE_API_KEY="sk-xxx"
"""

import os
import re
import json
import time
import logging
import argparse

from openai import OpenAI

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ── LLM 客户端 ────────────────────────────────────────────────────────────────
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
MODEL = os.getenv("AGENT_MODEL", "qwen-max")
# client = OpenAI(
#     api_key=os.getenv("DEEPSEEK_API_KEY"),
#     base_url="https://api.deepseek.com",
# )
# MODEL = os.getenv("AGENT_MODEL", "deepseek-v4-flash")


# ── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """你是一个专业的A股金融分析助手，可以使用以下工具来回答问题：

工具列表：
1. rag_search(query) - 在年报中语义检索文本内容（战略/财务数据/风险因素等）
2. company_lookup(name) - 将公司名称转换为股票代码
3. calculator(expr) - 计算数学表达式（支持四则运算和math函数）
4. financial_indicator(symbol) - 获取实时财务指标（PE/PB/ROE等）
5. stock_price(symbol, start_date, end_date) - 获取历史股价，日期格式YYYYMMDD

你必须严格按照以下格式交替输出，每次只能调用一个工具：

Thought: 分析当前状态，决定下一步做什么
Action: 工具名称
Action Input: {"参数名": "参数值"}

收到工具结果后继续推理，直到可以给出最终答案：

Thought: 已有足够信息
Final Answer: 完整的回答（含数据来源）

规则：
- 必须先用 company_lookup 获取股票代码，再调用 financial_indicator 或 stock_price
- 数字计算必须用 calculator，不能心算
- Final Answer 必须引用具体数据来源（哪份年报哪一页，或AkShare实时数据）
- 如果没有合适工具能回答，直接输出 Final Answer 说明原因
"""

# ── 格式解析 ──────────────────────────────────────────────────────────────────
_THOUGHT_RE      = re.compile(r"Thought:\s*(.+?)(?=\nAction:|\nFinal Answer:|$)", re.DOTALL)
_ACTION_RE       = re.compile(r"Action:\s*(\w+)")
_ACTION_INPUT_RE = re.compile(r"Action Input:\s*(\{.+?\})", re.DOTALL)
_FINAL_RE        = re.compile(r"Final Answer:\s*(.+)", re.DOTALL)


def _parse_step(text: str) -> dict:
    """从 LLM 输出中解析一步的结构化内容"""
    final = _FINAL_RE.search(text)
    if final:
        thought_m = _THOUGHT_RE.search(text)
        return {
            "type":    "final",
            "thought": thought_m.group(1).strip() if thought_m else "",
            "answer":  final.group(1).strip(),
        }

    thought_m = _THOUGHT_RE.search(text)
    action_m  = _ACTION_RE.search(text)
    input_m   = _ACTION_INPUT_RE.search(text)

    if not action_m:
        return {"type": "unparseable", "raw": text}

    try:
        action_input = json.loads(input_m.group(1)) if input_m else {}
    except json.JSONDecodeError:
        action_input = {}

    return {
        "type":         "action",
        "thought":      thought_m.group(1).strip() if thought_m else "",
        "action":       action_m.group(1).strip(),
        "action_input": action_input,
    }


# ── ReAct 核心循环 ─────────────────────────────────────────────────────────────

class _StreamRun:
    """
    可迭代包装：对外呈现为流式生成器，同时把最终的 messages 列表挂在 .messages 属性上。

    用法：
        result = run(question, max_steps=10, history=prev_messages)
        for step in result:        # 流式拿到每一步
            ...
        final_messages = result.messages   # 迭代结束后可访问，供下一轮 history
    """
    def __init__(self, gen, messages_ref: list):
        self._gen = gen
        self.messages = messages_ref

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._gen)


def run(question: str, max_steps: int = 10, history: list | None = None) -> _StreamRun:
    """
    执行 ReAct 循环，返回一个可迭代对象 _StreamRun。

    流式语义：每完成一步即可在 for 循环中拿到该步 dict，服务器可在拿到后立即推送 SSE。

    多轮语义：迭代结束后通过 result.messages 获取完整的 messages 列表，
    将其作为下一轮的 history 传入即可。

    Args:
        question:  当前轮的用户问题
        max_steps: 最大步数
        history:   上一轮返回的 result.messages（可为 None）

    Yields:
        step dict，type ∈ {"action", "final", "error", "max_steps"}

    Returns (via attribute):
        result.messages: 当前轮的完整 LLM messages 历史
    """
    from tools import TOOLS_MAP

    # 复制入参 history，避免修改调用方持有的列表
    # 注意：第一轮 (history 为空) 才追加 system prompt；多轮时 system 已存在于 history 中
    messages: list[dict] = list(history) if history else []
    if not messages:
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
    messages.append({"role": "user",   "content": question})

    def _gen():
        for step in range(1, max_steps + 1):
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0,
                stop=["Observation:"],  # 让模型停在调用工具前
            )
            llm_output = response.choices[0].message.content.strip()
            parsed = _parse_step(llm_output)
#防御性编程 防止解析失败
            if parsed["type"] == "final":
                yield {
                    "step":    step,
                    "type":    "final",
                    "thought": parsed["thought"],
                    "answer":  parsed["answer"],
                }
                return

            if parsed["type"] == "unparseable":
                yield {
                    "step":        step,
                    "type":        "error",
                    "observation": f"格式解析失败，原始输出：{llm_output[:200]}",
                }
                return

            # 执行工具
            tool_name  = parsed["action"]
            tool_args  = parsed["action_input"]
            tool_fn    = TOOLS_MAP.get(tool_name)

            if tool_fn is None:
                observation = f"未知工具 '{tool_name}'，可用工具：{list(TOOLS_MAP.keys())}"
            else:
                try:
                    observation = tool_fn(**tool_args)
                except TypeError as e:
                    observation = f"工具参数错误: {e}"

            step_result = {
                "step":         step,
                "type":         "action",
                "thought":      parsed["thought"],
                "action":       tool_name,
                "action_input": tool_args,
                "observation":  str(observation),
            }
            yield step_result

            # 将本步结果追加到对话历史
            messages.append({"role": "assistant", "content": llm_output})
            messages.append({
                "role":    "user",
                "content": f"Observation: {observation}\n",
            })

        # 超出最大步数，强制终止
        yield {
            "step":   max_steps + 1,
            "type":   "max_steps",
            "answer": f"已达最大步数 {max_steps}，未能得出最终答案",
        }

    return _StreamRun(_gen(), messages)


# ── CLI 打印 ──────────────────────────────────────────────────────────────────

COLORS = {
    "thought":  "\033[36m",   # cyan
    "action":   "\033[33m",   # yellow
    "obs":      "\033[32m",   # green
    "final":    "\033[35m",   # magenta
    "error":    "\033[31m",   # red
    "reset":    "\033[0m",
}

def _c(color: str, text: str) -> str:
    return f"{COLORS[color]}{text}{COLORS['reset']}"


def run_and_print(question: str, max_steps: int = 10, history: list | None = None):
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    print(f"模型: {MODEL}  实现: 手写Prompt解析")
    if history:
        print(f"[多轮模式] 已加载 {len(history)} 条历史消息")
    print('='*60)

    start = time.time()
    step_count = 0
    result = run(question, max_steps=max_steps, history=history)

    for step_data in result:  # 流式：每步产生后立即打印
        step_count += 1
        stype = step_data["type"]

        if stype == "action":
            print(f"\n[Step {step_data['step']}]")
            print(_c("thought", f"🧠 Thought: {step_data['thought']}"))
            print(_c("action",  f"🔧 Action:  {step_data['action']}"))
            print(_c("action",  f"   Input:   {json.dumps(step_data['action_input'], ensure_ascii=False)}"))
            print(_c("obs",     f"👁  Obs:     {step_data['observation'][:300]}"))

        elif stype == "final":
            elapsed = time.time() - start
            print(f"\n{'─'*60}")
            if step_data.get("thought"):
                print(_c("thought", f"🧠 Thought: {step_data['thought']}"))
            print(_c("final",  f"\n✅ Final Answer:\n{step_data['answer']}"))
            print(f"\n共 {step_data['step']} 步，耗时 {elapsed:.1f}s")

        elif stype in ("error", "max_steps"):
            print(_c("error", f"\n⚠️  {step_data.get('answer', step_data.get('observation', ''))}"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--question",  default="贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？")
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument("--history",   default=None, help="上一轮返回的 messages（JSON 字符串），用于多轮对话")
    args = parser.parse_args()
    history = json.loads(args.history) if args.history else None
    run_and_print(args.question, args.max_steps, history=history)










"""
Function Calling API 版 ReAct Agent

教学重点：
  1. 与手写版对比：框架帮你处理格式解析，但 Thought 过程在内部不可见
  2. tool_choice="auto" 让模型自己决定调用哪个工具或直接回答
  3. finish_reason 判断：tool_calls 表示继续调用，stop 表示给出最终答案
  4. 相同工具集，相同问题，对比两种实现的稳定性和步骤数

使用方式：
  python react_function_calling.py
  python react_function_calling.py --question "茅台近一年股价涨跌幅如何？"
  python react_function_calling.py --question "..." --max_steps 8

依赖：
  pip install openai faiss-cpu sentence-transformers akshare
  export DASHSCOPE_API_KEY="sk-xxx"
"""

import os
import json
import time
import logging
import argparse

from openai import OpenAI

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# client = OpenAI(
#     api_key=os.getenv("DASHSCOPE_API_KEY"),
#     base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
# )
# MODEL = os.getenv("AGENT_MODEL", "qwen-max")
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)
MODEL = os.getenv("AGENT_MODEL", "deepseek-v4-flash")

FC_SYSTEM_PROMPT = """你是一个专业的A股金融分析助手。
规则：
- 调用 financial_indicator 或 stock_price 之前，必须先用 company_lookup 获取股票代码
- 数字计算必须使用 calculator 工具，不能心算
- Final Answer 必须引用具体数据来源
- 如果没有合适工具能回答，直接说明原因
"""


# ── ReAct 核心循环 ─────────────────────────────────────────────────────────────

class _StreamRun:
    """
    可迭代包装：对外呈现为流式生成器，同时把最终的 messages 列表挂在 .messages 属性上。

    用法：
        result = run(question, max_steps=10, history=prev_messages)
        for step in result:        # 流式拿到每一步
            ...
        final_messages = result.messages   # 迭代结束后可访问，供下一轮 history
    """
    def __init__(self, gen, messages_ref: list):
        self._gen = gen
        self.messages = messages_ref

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._gen)


def run(question: str, max_steps: int = 10, history: list | None = None) -> _StreamRun:
    """
    执行 Function Calling 版 ReAct 循环，返回 _StreamRun 可迭代对象。

    流式语义：每完成一个工具调用（或直接给出 Final Answer）即可在 for 循环中拿到
    对应的 step dict，服务器可在拿到后立即推送 SSE。

    多轮语义：迭代结束后通过 result.messages 获取完整的 messages 列表
    （含 assistant 的 tool_calls 字段和 tool role 消息），
    将其作为下一轮的 history 传入即可。
    """
    from tools import TOOLS_MAP, TOOLS_SCHEMA

    # 复制入参 history，避免修改调用方持有的列表
    # 注意：第一轮 (history 为空) 才追加 system prompt；多轮时 system 已存在于 history 中
    messages: list[dict] = list(history) if history else []
    if not messages:
        messages.append({"role": "system", "content": FC_SYSTEM_PROMPT})
    messages.append({"role": "user",   "content": question})

    def _gen():
        for step in range(1, max_steps + 1):
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                temperature=0,
            )
            msg    = response.choices[0].message
            reason = response.choices[0].finish_reason

            # 把 assistant 消息（含 tool_calls 字段）以 dict 形式写入历史
            # 注意：openai 客户端的 ChatCompletionMessage 是 Pydantic 模型，.model_dump() 可序列化
            try:
                msg_dict = msg.model_dump(exclude_none=True)
            except AttributeError:
                # 兼容老版本 openai 库
                msg_dict = {
                    "role":       msg.role,
                    "content":    msg.content,
                    "tool_calls": [
                        {
                            "id":       tc.id,
                            "type":     tc.type,
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in (msg.tool_calls or [])
                    ],
                }

            # 模型决定直接回答（无工具调用）
            if reason == "stop" or not msg.tool_calls:
                yield {
                    "step":   step,
                    "type":   "final",
                    "thought": "",
                    "answer": msg.content or "（模型返回空内容）",
                }
                # 把最终的 assistant 消息也写回历史，保证 messages 完整
                messages.append(msg_dict)
                return

            # 模型请求调用工具 —— 把 assistant 消息加入历史
            messages.append(msg_dict)

            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                tool_fn = TOOLS_MAP.get(tool_name)
                if tool_fn is None:
                    observation = f"未知工具 '{tool_name}'"
                else:
                    try:
                        observation = tool_fn(**tool_args)
                    except TypeError as e:
                        observation = f"工具参数错误: {e}"

                step_result = {
                    "step":         step,
                    "type":         "action",
                    "thought":      "",   # Function Calling 版 Thought 在模型内部，不可见
                    "action":       tool_name,
                    "action_input": tool_args,
                    "observation":  str(observation),
                }
                yield step_result

                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      str(observation),
                })

        # 超出最大步数
        yield {
            "step":   max_steps + 1,
            "type":   "max_steps",
            "answer": f"已达最大步数 {max_steps}，未能得出最终答案",
        }

    return _StreamRun(_gen(), messages)


# ── CLI 打印（复用 react_manual 的彩色输出） ───────────────────────────────────

COLORS = {
    "thought": "\033[36m",
    "action":  "\033[33m",
    "obs":     "\033[32m",
    "final":   "\033[35m",
    "error":   "\033[31m",
    "reset":   "\033[0m",
}

def _c(color: str, text: str) -> str:
    return f"{COLORS[color]}{text}{COLORS['reset']}"


def run_and_print(question: str, max_steps: int = 10, history: list | None = None):
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    print(f"模型: {MODEL}  实现: Function Calling")
    if history:
        print(f"[多轮模式] 已加载 {len(history)} 条历史消息")
    print('='*60)

    start = time.time()
    result = run(question, max_steps=max_steps, history=history)

    for step_data in result:  # 流式：每步产生后立即打印
        stype = step_data["type"]

        if stype == "action":
            print(f"\n[Step {step_data['step']}]")
            # Thought 在 FC 版不可见，显示提示
            print(_c("thought", "🧠 Thought: （模型内部推理，Function Calling 版不可见）"))
            print(_c("action",  f"🔧 Action:  {step_data['action']}"))
            print(_c("action",  f"   Input:   {json.dumps(step_data['action_input'], ensure_ascii=False)}"))
            print(_c("obs",     f"👁  Obs:     {step_data['observation'][:300]}"))

        elif stype == "final":
            elapsed = time.time() - start
            print(f"\n{'─'*60}")
            print(_c("final", f"\n✅ Final Answer:\n{step_data['answer']}"))
            print(f"\n共 {step_data['step']} 步，耗时 {elapsed:.1f}s")

        elif stype in ("error", "max_steps"):
            print(_c("error", f"\n⚠️  {step_data.get('answer', '')}"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--question",  default="贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？")
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument("--history",   default=None, help="上一轮返回的 messages（JSON 字符串），用于多轮对话")
    args = parser.parse_args()
    history = json.loads(args.history) if args.history else None
    run_and_print(args.question, args.max_steps, history=history)
