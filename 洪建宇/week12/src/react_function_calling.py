"""
Function Calling API 版 ReAct Agent（支持多轮问答）

教学重点：
  1. 与手写版对比：框架帮你处理格式解析，但 Thought 过程在内部不可见
  2. tool_choice="auto" 让模型自己决定调用哪个工具或直接回答
  3. finish_reason 判断：tool_calls 表示继续调用，stop 表示给出最终答案
  4. 相同工具集，相同问题，对比两种实现的稳定性和步骤数
  5. 多轮问答：通过 ReactAgent 类封装对话状态，保留上下文历史

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
from typing import Generator, List, Dict, Any

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


class ReactAgent:
    """
    ReAct Agent 类，支持多轮对话

    使用示例：
        agent = ReactAgent(max_steps=10)
        for step in agent.ask("茅台2023年毛利率是多少？"):
            print(step)
        # 继续追问
        for step in agent.ask("五粮液的呢？"):
            print(step)
        # 重置对话
        agent.reset()
    """

    def __init__(self, max_steps: int = 10):
        self.max_steps = max_steps
        self.messages: List[Dict[str, Any]] = [
            {"role": "system", "content": FC_SYSTEM_PROMPT},
        ]
        self.step_counter = 0

    def reset(self):
        """重置对话状态，清空历史记录"""
        self.messages = [
            {"role": "system", "content": FC_SYSTEM_PROMPT},
        ]
        self.step_counter = 0

    def ask(self, question: str) -> Generator[dict, None, None]:
        """
        执行一轮问答，yield 每一步结构化结果

        Args:
            question: 用户问题

        Returns:
            Generator yielding step results
        """
        from tools import TOOLS_MAP, TOOLS_SCHEMA

        # 追加用户问题到对话历史
        self.messages.append({"role": "user", "content": question})

        for turn_step in range(1, self.max_steps + 1):
            self.step_counter += 1

            response = client.chat.completions.create(
                model=MODEL,
                messages=self.messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                temperature=0,
            )
            msg = response.choices[0].message
            reason = response.choices[0].finish_reason

            # 模型决定直接回答（无工具调用）
            if reason == "stop" or not msg.tool_calls:
                answer = msg.content or "（模型返回空内容）"

                # 将最终回复追加到对话历史，支持多轮问答
                self.messages.append({
                    "role": "assistant",
                    "content": answer,
                })

                yield {
                    "step": turn_step,
                    "type": "final",
                    "thought": "",
                    "answer": answer,
                }
                return

            # 模型请求调用工具 - 将 msg 转为 dict 确保跨轮序列化正确
            self.messages.append(msg.model_dump())

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
                    "step": turn_step,
                    "type": "action",
                    "thought": "",  # Function Calling 版 Thought 在模型内部，不可见
                    "action": tool_name,
                    "action_input": tool_args,
                    "observation": str(observation),
                }
                yield step_result

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(observation),
                })

        yield {
            "step": self.max_steps + 1,
            "type": "max_steps",
            "answer": f"已达最大步数 {self.max_steps}，未能得出最终答案",
        }


# ── 向后兼容入口 ────────────────────────────────────────────────────────────────

def run(question: str, max_steps: int = 10) -> Generator[dict, None, None]:
    """
    执行 Function Calling 版 ReAct 循环（单次问答，向后兼容）
    格式与 react_manual.run() 保持一致，便于 evaluate.py 统一对比
    """
    agent = ReactAgent(max_steps=max_steps)
    yield from agent.ask(question)


# ── CLI 打印（支持多轮对话） ──────────────────────────────────────────────────

COLORS = {
    "thought": "\033[36m",
    "action": "\033[33m",
    "obs": "\033[32m",
    "final": "\033[35m",
    "error": "\033[31m",
    "reset": "\033[0m",
}


def _c(color: str, text: str) -> str:
    return f"{COLORS[color]}{text}{COLORS['reset']}"


def print_step(step_data: dict):
    """打印单步结果"""
    stype = step_data["type"]

    if stype == "action":
        print(f"\n[Step {step_data['step']}]")
        print(_c("thought", "🧠 Thought: （模型内部推理，Function Calling 版不可见）"))
        print(_c("action", f"🔧 Action:  {step_data['action']}"))
        print(_c("action", f"   Input:   {json.dumps(step_data['action_input'], ensure_ascii=False)}"))
        print(_c("obs", f"👁  Obs:     {step_data['observation'][:300]}"))

    elif stype == "final":
        print(f"\n{'─' * 60}")
        print(_c("final", f"\n✅ Final Answer:\n{step_data['answer']}"))

    elif stype in ("error", "max_steps"):
        print(_c("error", f"\n⚠️  {step_data.get('answer', '')}"))


def run_and_print(question: str = None, max_steps: int = 10):
    """
    运行问答并打印结果（支持单轮或多轮模式）

    如果提供了 question 参数，执行单轮问答；
    如果未提供 question 参数，进入交互式多轮问答模式。
    """
    agent = ReactAgent(max_steps=max_steps)

    if question:
        # 单轮模式
        print(f"\n{'=' * 60}")
        print(f"问题: {question}")
        print(f"模型: {MODEL}  实现: Function Calling")
        print('=' * 60)

        start = time.time()
        for step_data in agent.ask(question):
            print_step(step_data)
        elapsed = time.time() - start
        print(f"\n共 {agent.step_counter} 步，耗时 {elapsed:.1f}s")
    else:
        # 交互式多轮模式
        print(f"\n{'=' * 60}")
        print(f"🤖 ReAct Financial Agent (多轮模式)")
        print(f"模型: {MODEL}  实现: Function Calling")
        print(f"输入 'quit' 或 'exit' 退出，输入 'reset' 重置对话")
        print('=' * 60)

        while True:
            try:
                question_input = input("\n❓ 请输入问题：").strip()
            except EOFError:
                print("\n👋 再见！")
                break

            if not question_input:
                continue

            if question_input.lower() in ("quit", "exit"):
                print("👋 再见！")
                break

            if question_input.lower() == "reset":
                agent.reset()
                print("🔄 对话已重置")
                continue

            start = time.time()
            for step_data in agent.ask(question_input):
                print_step(step_data)
            elapsed = time.time() - start
            print(f"\n本轮共 {agent.step_counter} 步，耗时 {elapsed:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default=None,
                        help="问题（不提供则进入交互式多轮模式）")
    parser.add_argument("--max_steps", type=int, default=10)
    args = parser.parse_args()
    run_and_print(args.question, args.max_steps)
