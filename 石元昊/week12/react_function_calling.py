"""
Function Calling API 版 ReAct Agent —— 多轮对话版

教学重点：
  1. 与手写版对比：框架处理格式解析，但 Thought 过程在内部不可见
  2. 多轮对话：messages 跨轮共享，tool_calls 中间步骤在回答完成后清理，
     只保留 user 问题 + assistant 最终答案，避免上下文膨胀
  3. tool_choice="auto" 让模型自主决定调用工具或直接回答
  4. 支持 /clear 清空历史、/history 查看对话摘要、/quit 退出

使用方式：
  python react_function_calling.py                       # 交互式多轮对话
  python react_function_calling.py --question "..."      # 单轮模式

依赖：
  pip install openai faiss-cpu sentence-transformers akshare
  export DEEPSEEK_API_KEY="sk-xxx"
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
- 注意对话历史中的上下文，用户可能会追问或省略主语，请结合前文理解
"""


def run(
    question: str,
    messages: list[dict],
    max_steps: int = 10,
) -> Generator[dict, None, None]:
    """
    执行一轮 Function Calling 版 ReAct 循环，yield 每一步结构化结果。

    与原版区别：
      - messages 由外部传入并在多轮间共享
      - 本轮 tool_calls 中间消息在回答完成后清理，
        只保留 user 问题 + assistant 最终答案
    """
    from tools import TOOLS_MAP, TOOLS_SCHEMA

    messages.append({"role": "user", "content": question})
    react_start_len = len(messages)

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
            # 清理本轮中间消息
            del messages[react_start_len:]
            messages.append({"role": "assistant", "content": answer})
            yield {
                "step":   step,
                "type":   "final",
                "thought": "",
                "answer": answer,
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
                "thought":      "",
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
    del messages[react_start_len:]
    messages.append({"role": "assistant", "content": "（达到最大步数限制）"})
    yield {
        "step":   max_steps + 1,
        "type":   "max_steps",
        "answer": f"已达最大步数 {max_steps}，未能得出最终答案",
    }


# ── 多轮对话会话管理 ──────────────────────────────────────────────────────────

class ChatSession:
    """
    管理 Function Calling 版的多轮对话。

    设计要点：
      - messages[0] 固定为 system prompt
      - 每轮 tool_calls 中间步骤在回答完成后被清理，
        只保留 user 问题 + assistant 最终答案
      - 支持 /clear 重置、/history 查看摘要
    """

    def __init__(self, max_steps: int = 10):
        self.messages: list[dict] = [{"role": "system", "content": FC_SYSTEM_PROMPT}]
        self.max_steps = max_steps
        self.turn_count = 0

    def ask(self, question: str) -> Generator[dict, None, None]:
        self.turn_count += 1
        yield from run(question, self.messages, max_steps=self.max_steps)

    def clear(self):
        self.messages = [self.messages[0]]
        self.turn_count = 0

    def history_summary(self) -> str:
        lines = []
        turn = 0
        for msg in self.messages:
            if msg["role"] == "user":
                turn += 1
                lines.append(f"[轮次 {turn}] 用户: {msg['content'][:80]}")
            elif msg["role"] == "assistant":
                lines.append(f"       助手: {msg['content'][:80]}")
        return "\n".join(lines) if lines else "（暂无对话历史）"


# ── CLI 打印 ──────────────────────────────────────────────────────────────────

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


def run_and_print(question: str, max_steps: int = 10):
    """单轮兼容接口"""
    session = ChatSession(max_steps=max_steps)
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    print(f"模型: {MODEL}  实现: Function Calling（多轮版）")
    print('='*60)

    start = time.time()
    for step_data in session.ask(question):
        stype = step_data["type"]
        if stype == "action":
            print(f"\n[Step {step_data['step']}]")
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


def run_interactive(max_steps: int = 10):
    """交互式多轮对话入口"""
    session = ChatSession(max_steps=max_steps)

    print(f"\n{'='*60}")
    print(f"🤖 A股金融分析助手（多轮对话模式）")
    print(f"   模型: {MODEL}  实现: Function Calling")
    print(f"   输入 /clear 清空历史 | /history 查看对话 | /quit 退出")
    print('='*60)

    while True:
        try:
            question = input("\n📝 你的问题: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not question:
            continue

        if question == "/quit":
            print("再见！")
            break

        if question == "/clear":
            session.clear()
            print("✅ 对话历史已清空")
            continue

        if question == "/history":
            print(f"\n{session.history_summary()}")
            continue

        print(f"\n{'─'*60}")
        print(f"[轮次 {session.turn_count + 1}]")
        start = time.time()

        for step_data in session.ask(question):
            stype = step_data["type"]
            if stype == "action":
                print(f"\n[Step {step_data['step']}]")
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
    parser.add_argument("--question",  default=None, help="指定问题（单轮模式）；不指定则进入交互式多轮对话")
    parser.add_argument("--max_steps", type=int, default=10)
    args = parser.parse_args()

    if args.question:
        run_and_print(args.question, args.max_steps)
    else:
        run_interactive(args.max_steps)
