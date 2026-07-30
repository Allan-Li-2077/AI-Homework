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
from typing import Generator, Any

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

在调用工具之前，请先输出你的思考过程，格式如下：

思考：分析当前状态，解释下一步的计划和理由。

然后调用相应的工具。收到工具结果后，继续分析并决定下一步。

规则：
- 调用 financial_indicator 或 stock_price 之前，必须先用 company_lookup 获取股票代码
- 数字计算必须使用 calculator 工具，不能心算
- Final Answer 必须引用具体数据来源
- 如果没有合适工具能回答，直接说明原因
"""


# ── 上下文窗口裁剪 ────────────────────────────────────────────────────────────

def _ensure_context_window(messages: list[dict], max_chars: int = 24000) -> None:
    """
    当消息总长度超出 max_chars 时，移除最早的非 system 消息，
    防止长对话撑爆 LLM 上下文窗口。

    成对移除 strategy：
      删除最旧的一轮 (assistant + tool) 消息，
      避免拆散 tool_calls 与其对应的 tool 结果，
      否则 OpenAI API 会因孤立 tool 消息而报错。
    """
    total = sum(len(str(m.get("content", ""))) for m in messages)
    if total <= max_chars or len(messages) <= 3:
        return
    while len(messages) > 3 and total > max_chars:
        # 成对删除最早的非 system 消息及其紧邻的 tool 消息（如果有）
        idx = 2
        removed = messages.pop(idx)
        total -= len(str(removed.get("content", "")))
        # 如果下一条是 tool 消息，一起删除（保持配对完整性）
        if idx < len(messages) and messages[idx].get("role") == "tool":
            removed2 = messages.pop(idx)
            total -= len(str(removed2.get("content", "")))


# ── ReAct 核心循环 ─────────────────────────────────────────────────────────────

def run(question: str | None = None,
        messages: list[dict] | None = None,
        max_steps: int = 10) -> Generator[dict, None, None]:
    """
    执行 Function Calling 版 ReAct 循环，yield 每一步结构化结果

    格式与 react_manual.run() 保持一致，便于 evaluate.py 统一对比
    """
    from tools import TOOLS_MAP, TOOLS_SCHEMA

    # 支持多轮对话：传入 messages 则追加问题，否则全新对话
    if messages is not None:
        conv = list(messages)
        if question is not None:
            conv.append({"role": "user", "content": question})
    else:
        conv = [
            {"role": "system", "content": FC_SYSTEM_PROMPT},
            {"role": "user",   "content": question or ""},
        ]

    for step in range(1, max_steps + 1):
        # 上下文窗口裁剪（每次 API 调用前，确保 conv 不超长）
        _ensure_context_window(conv)
        response = client.chat.completions.create(
            model=MODEL,
            messages=conv,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0,
        )
        msg    = response.choices[0].message
        reason = response.choices[0].finish_reason

        # 模型决定直接回答（无工具调用）
        if reason == "stop" or not msg.tool_calls:
            final_thought = msg.content.strip() if msg.content else ""
            conv.append(msg.model_dump())
            yield {
                "step":   step,
                "type":   "final",
                "thought": final_thought,
                "answer": msg.content or "（模型返回空内容）",
            }
            yield {"type": "conversation", "messages": conv}
            return

        # 模型请求调用工具
        conv.append(msg.model_dump())

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

            # 从 msg.content 提取推理过程（很多模型同时返回 content + tool_calls）
            thought = msg.content.strip() if msg.content else ""

            step_result = {
                "step":         step,
                "type":         "action",
                "thought":      thought,
                "action":       tool_name,
                "action_input": tool_args,
                "observation":  str(observation),
            }
            yield step_result

            conv.append({
                "role":         "tool",
                "tool_call_id": tool_call.id,
                "content":      str(observation),
            })

    # 超出最大步数，强制终止
    conv.append({"role": "assistant", "content": "（已达最大步数，未能得出最终答案）"})
    yield {
        "step":   max_steps + 1,
        "type":   "max_steps",
        "answer": f"已达最大步数 {max_steps}，未能得出最终答案",
    }
    yield {"type": "conversation", "messages": conv}


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


def run_and_print(question: str, max_steps: int = 10, messages: list[dict] | None = None) -> list[dict] | None:
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    print(f"模型: {MODEL}  实现: Function Calling")
    print('='*60)

    start = time.time()
    conv = messages

    for step_data in run(question, max_steps=max_steps, messages=messages):
        stype = step_data["type"]

        if stype == "conversation":
            conv = step_data["messages"]
            continue

        if stype == "action":
            print(f"\n[Step {step_data['step']}]")
            thought_text = step_data.get("thought") or "（模型未返回推理过程）"
            print(_c("thought", f"🧠 Thought: {thought_text}"))
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

    return conv


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--question",  default="贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？")
    parser.add_argument("--max_steps", type=int, default=10)
    args = parser.parse_args()
    run_and_print(args.question, args.max_steps)
