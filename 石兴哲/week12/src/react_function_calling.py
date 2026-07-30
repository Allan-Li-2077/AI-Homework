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

# ── LLM 客户端工厂 ──────────────────────────────────────────────────────────────
def _get_default_client() -> OpenAI:
    """创建默认 LLM 客户端，供 ReActSession 和独立 run() 复用"""
    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )


_client: OpenAI | None = None
MODEL = os.getenv("AGENT_MODEL", "deepseek-v4-flash")


def _default_client() -> OpenAI:
    """懒加载全局客户端（向后兼容）"""
    global _client
    if _client is None:
        _client = _get_default_client()
    return _client


FC_SYSTEM_PROMPT = """你是一个专业的A股金融分析助手。
规则：
- 调用 financial_indicator 或 stock_price 之前，必须先用 company_lookup 获取股票代码
- 数字计算必须使用 calculator 工具，不能心算
- Final Answer 必须引用具体数据来源
- 如果没有合适工具能回答，直接说明原因
"""


# ── ReActSession：跨问答持久化工作记忆 ──────────────────────────────────────────

class SessionBusyError(RuntimeError):
    """同一 session 同时只允许一个 run() 执行"""


class ReActSession:
    """会话级 ReAct Agent，跨多次问答保持对话记忆。

    使用方式::

        session = ReActSession()
        for step in session.run("茅台2023年毛利率？"):
            print(step)
        for step in session.run("那五粮液呢？"):   # 自动记住上文
            print(step)
        session.reset()   # 清除历史

    Parameters
    ----------
    system_prompt:
        自定义 system prompt，默认使用 FC_SYSTEM_PROMPT
    model:
        模型名，默认读取 AGENT_MODEL 环境变量
    client:
        自定义 OpenAI 客户端，默认使用 DeepSeek API
    max_context_messages:
        触发上下文压缩的消息数阈值，默认 50
    """

    def __init__(
        self,
        system_prompt: str | None = None,
        model: str | None = None,
        client: OpenAI | None = None,
        max_context_messages: int = 50,
    ):
        self.client = client or _get_default_client()
        self.model = model or MODEL
        self.system_prompt = system_prompt or FC_SYSTEM_PROMPT
        self.max_context_messages = max_context_messages
        self.messages: list[dict] = [
            {"role": "system", "content": self.system_prompt}
        ]
        self._qa_history: list[dict] = []
        self._active = False

    # ── 核心方法 ────────────────────────────────────────────────────────────

    def run(self, question: str, max_steps: int = 10) -> Generator[dict, None, None]:
        """在已有对话历史上继续推理。

        yield 的 dict 格式与模块级 run() 完全一致：
        - action:  {"step": int, "type": "action", "thought": str, "action": str,
                     "action_input": dict, "observation": str}
        - final:   {"step": int, "type": "final", "thought": str, "answer": str}
        - error:   {"step": int, "type": "max_steps", "answer": str}
        """
        if self._active:
            raise SessionBusyError(
                "此 session 正在执行另一个问题，请等待完成后再提问"
            )
        self._active = True

        from tools import TOOLS_MAP, TOOLS_SCHEMA

        # 上下文窗口管理：消息过多时压缩旧历史
        self._maybe_compact()

        # 追加新问题
        self.messages.append({"role": "user", "content": question})

        final_answer = None

        try:
            for step in range(1, max_steps + 1):
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto",
                    temperature=0,
                )
                msg = response.choices[0].message
                reason = response.choices[0].finish_reason

                # 模型决定直接回答（无工具调用）
                if reason == "stop" or not msg.tool_calls:
                    final_answer = msg.content or "（模型返回空内容）"
                    self.messages.append({"role": "assistant", "content": final_answer})
                    yield {
                        "step": step,
                        "type": "final",
                        "thought": "",
                        "answer": final_answer,
                    }
                    break

                # 模型请求调用工具
                self.messages.append(msg)

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
                        "step": step,
                        "type": "action",
                        "thought": "",
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

            else:
                # 超出最大步数
                final_answer = f"已达最大步数 {max_steps}，未能得出最终答案"
                yield {
                    "step": max_steps + 1,
                    "type": "max_steps",
                    "answer": final_answer,
                }

        finally:
            self._active = False
            # 记录本轮 Q&A
            if final_answer is not None:
                self._qa_history.append({
                    "question": question,
                    "answer": final_answer[:500],  # 截断保存，避免过大
                    "messages_count": len(self.messages),
                })

    def reset(self) -> None:
        """清除所有对话历史，仅保留 system prompt。"""
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self._qa_history.clear()

    @property
    def history(self) -> list[dict]:
        """返回历史 Q&A 摘要列表（只读副本）。"""
        return list(self._qa_history)

    @property
    def message_count(self) -> int:
        """当前消息列表中的消息数（含 system prompt）。"""
        return len(self.messages)

    # ── 内部方法 ────────────────────────────────────────────────────────────

    def _maybe_compact(self) -> None:
        """当消息数超过阈值时，压缩旧对话历史为一条摘要消息。

        策略：保留 system prompt，取最近 2 轮 Q&A 的原始消息保留，
        对其余更早的消息调用 LLM 做摘要，替换为一条 user 消息。
        如果压缩失败（如 LLM 不可用），则不做任何操作，宁可不压缩也不错删。
        """
        if len(self.messages) <= self.max_context_messages:
            return

        # 估算最近 2 轮 Q&A 占用的消息数（每轮约 user + assistant + N*tool）
        # 保守估计：保留最近 30 条消息（约 2-3 轮完整交互）
        keep_count = min(30, len(self.messages) - 5)
        old_messages = self.messages[1:-keep_count]   # 跳过 system prompt
        recent_messages = self.messages[-keep_count:]

        if len(old_messages) < 4:
            return  # 太少不值得压缩

        try:
            # 构造摘要请求
            conv_text = _messages_to_text(old_messages)
            summary_prompt = (
                "请将以下用户与金融分析助手的对话历史总结为一段简洁的摘要，"
                "保留所有关键事实、数字、公司名称和结论。仅输出摘要内容，不要加任何前缀。\n\n"
                f"{conv_text}"
            )
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": summary_prompt}],
                temperature=0,
                max_tokens=500,
            )
            summary = resp.choices[0].message.content or ""
            if summary.strip():
                self.messages = [
                    self.messages[0],  # system prompt
                    {"role": "user", "content": f"[历史对话摘要]\n{summary.strip()}"},
                ] + recent_messages
                logger.info(
                    "上下文压缩完成：%d 条旧消息 → %d 字摘要，保留最近 %d 条消息",
                    len(old_messages), len(summary), len(recent_messages),
                )
        except Exception:
            logger.warning("上下文压缩失败，保持原消息不变", exc_info=True)

    def __repr__(self) -> str:
        return (
            f"ReActSession(model={self.model!r}, "
            f"questions={len(self._qa_history)}, "
            f"messages={len(self.messages)})"
        )


def _messages_to_text(messages: list[dict]) -> str:
    """将消息列表转换为可读文本，供摘要压缩使用。"""
    lines = []
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if role == "system":
            continue
        if role == "tool":
            # tool 消息截断前 300 字符
            content = str(content)[:300]
        lines.append(f"[{role}]: {content}")
    return "\n\n".join(lines)


def run(question: str, max_steps: int = 10) -> Generator[dict, None, None]:
    """
    执行 Function Calling 版 ReAct 循环，yield 每一步结构化结果

    格式与 react_manual.run() 保持一致，便于 evaluate.py 统一对比。

    注意：此函数每次调用创建临时 ReActSession——不同问题之间**无记忆**。
    如需跨问答持久化记忆，请直接使用 ReActSession 类。
    """
    session = ReActSession()
    yield from session.run(question, max_steps=max_steps)


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


def run_and_print(question: str, max_steps: int = 10):
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    print(f"模型: {MODEL}  实现: Function Calling")
    print('='*60)

    start = time.time()

    for step_data in run(question, max_steps=max_steps):
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
    args = parser.parse_args()
    run_and_print(args.question, args.max_steps)
