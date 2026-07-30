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
from typing import Generator

from openai import OpenAI

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

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

FC_SYSTEM_PROMPT = """你是一个专业的A股金融分析助手。
规则：
- 调用 financial_indicator 或 stock_price 之前，必须先用 company_lookup 获取股票代码
- 数字计算必须使用 calculator 工具，不能心算
- Final Answer 必须引用具体数据来源
- 如果没有合适工具能回答，直接说明原因
"""


def run(question: str, max_steps: int = 10,
        messages: list[dict] | None = None) -> Generator[dict, None, None]:
    """
    执行 Function Calling 版 ReAct 循环，yield 每一步结构化结果

    格式与 react_manual.run() 保持一致，便于 evaluate.py 统一对比

    参数:
        question:   用户问题
        max_steps:  最大步数
        messages:   可选，已有的消息历史。传入后会在其基础上追加 user 消息，
                    实现多轮对话上下文保持。调用方可通过返回值获取更新后的消息列表。
    """
    from tools import TOOLS_MAP, TOOLS_SCHEMA

    if messages is None:
        messages = [
            {"role": "system", "content": FC_SYSTEM_PROMPT},
        ]

    messages.append({"role": "user", "content": question})

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

        # 模型决定直接回答（无工具调用）
        if reason == "stop" or not msg.tool_calls:
            yield {
                "step":   step,
                "type":   "final",
                "thought": "",
                "answer": msg.content or "（模型返回空内容）",
            }
            return

        # 模型请求调用工具
        messages.append(msg)

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

    yield {
        "step":   max_steps + 1,
        "type":   "max_steps",
        "answer": f"已达最大步数 {max_steps}，未能得出最终答案",
    }


# ── 多轮对话 ──────────────────────────────────────────────────────────────────

def interactive_chat(max_steps: int = 10):
    """
    交互式多轮对话模式：维护完整消息历史，支持上下文追问。

    特点：
    - 首轮自动注入 system prompt
    - 每轮对话保留之前的工具调用和回答结果，模型能基于上下文回答
    - 输入 'quit' / 'exit' / 'q' 退出
    """
    from tools import TOOLS_MAP, TOOLS_SCHEMA

    messages = [
        {"role": "system", "content": FC_SYSTEM_PROMPT},
    ]

    print(f"\n{'='*60}")
    print(f"🤖 多轮对话模式已启动 (模型: {MODEL})")
    print(f"   输入 'quit' / 'exit' / 'q' 退出")
    print(f"{'='*60}")

    turn = 0
    while True:
        try:
            question = input(f"\n[第{turn + 1}轮] 👤 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("👋 再见！")
            break

        turn += 1
        messages.append({"role": "user", "content": question})

        start = time.time()

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

            # 模型决定直接回答（无工具调用）
            if reason == "stop" or not msg.tool_calls:
                answer = msg.content or "（模型返回空内容）"
                messages.append({"role": "assistant", "content": answer})
                elapsed = time.time() - start
                print(f"\n{'─'*60}")
                print(_c("final", f"🤖 Final Answer:\n{answer}"))
                print(f"共 {step} 步，耗时 {elapsed:.1f}s")
                break

            # 模型请求调用工具
            messages.append(msg)

            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                print(f"\n[Step {step}] 🔧 {tool_name}({json.dumps(tool_args, ensure_ascii=False)})")

                tool_fn = TOOLS_MAP.get(tool_name)
                if tool_fn is None:
                    observation = f"未知工具 '{tool_name}'"
                else:
                    try:
                        observation = tool_fn(**tool_args)
                    except TypeError as e:
                        observation = f"工具参数错误: {e}"

                obs_str = str(observation)
                print(_c("obs", f"   👁 Obs: {obs_str[:200]}{'...' if len(obs_str) > 200 else ''}"))

                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      obs_str,
                })
        else:
            # max_steps 耗尽
            print(_c("error", f"\n⚠️  已达最大步数 {max_steps}，未能得出最终答案"))
            messages.append({
                "role": "assistant",
                "content": f"（达到最大步数限制 {max_steps}，未能完成回答）"
            })


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


def run_and_print(question: str, max_steps: int = 10,
                  messages: list[dict] | None = None):
    """单轮问答模式（带彩色打印），可选传入 messages 以支持多轮上下文"""
    if messages is None:
        print(f"\n{'='*60}")
        print(f"问题: {question}")
        print(f"模型: {MODEL}  实现: Function Calling")
        print('='*60)

    start = time.time()

    for step_data in run(question, max_steps=max_steps, messages=messages):
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
    parser = argparse.ArgumentParser(
        description="Function Calling 版 ReAct 金融分析 Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 单轮问答
  python react_function_calling.py
  python react_function_calling.py --question "茅台近一年股价涨跌幅如何？"

  # 多轮交互对话
  python react_function_calling.py --interactive
  python react_function_calling.py -i
        """,
    )
    parser.add_argument("--question",    default="贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？")
    parser.add_argument("--max_steps",   type=int, default=10)
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="启动交互式多轮对话模式（支持上下文追问）")
    args = parser.parse_args()

    if args.interactive:
        interactive_chat(args.max_steps)
    else:
        run_and_print(args.question, args.max_steps)
