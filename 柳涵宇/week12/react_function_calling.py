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

from openai import APIConnectionError, APITimeoutError, OpenAI

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "dashscope").lower()
MODEL = os.getenv("AGENT_MODEL", "qwen-max")
_client = None
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _client_options() -> dict:
    if LLM_PROVIDER == "dashscope":
        return {
            "api_key": os.getenv("DASHSCOPE_API_KEY"),
            "base_url": os.getenv(
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            "timeout": float(os.getenv("DASHSCOPE_TIMEOUT", os.getenv("OPENAI_TIMEOUT", "120"))),
            "max_retries": int(os.getenv("OPENAI_MAX_RETRIES", "2")),
        }

    if LLM_PROVIDER == "ollama":
        return {
            "api_key": os.getenv("OLLAMA_API_KEY", "ollama"),
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
            "timeout": float(os.getenv("OLLAMA_TIMEOUT", os.getenv("OPENAI_TIMEOUT", "180"))),
            "max_retries": int(os.getenv("OPENAI_MAX_RETRIES", "2")),
        }

    kwargs = {
        "api_key": os.getenv("OPENAI_API_KEY"),
        "timeout": float(os.getenv("OPENAI_TIMEOUT", "120")),
        "max_retries": int(os.getenv("OPENAI_MAX_RETRIES", "2")),
    }
    if os.getenv("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.getenv("OPENAI_BASE_URL")
    return kwargs


def _llm_error_message(error: Exception) -> str:
    base_url = (
        os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        if LLM_PROVIDER == "dashscope"
        else os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
        if LLM_PROVIDER == "ollama"
        else os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    status_code = getattr(error, "status_code", None)
    if status_code is None and hasattr(error, "response"):
        status_code = getattr(error.response, "status_code", None)
    if status_code in RETRYABLE_STATUS_CODES:
        return (
            f"LLM 服务暂时不可用（HTTP {status_code}）：当前模型 {MODEL}，接口地址 {base_url}。"
            "已自动重试后仍失败，请检查服务状态/API Key，或切换可用模型。"
        )
    if isinstance(error, APIConnectionError) and LLM_PROVIDER == "ollama":
        return (
            f"无法连接 Ollama：接口地址 {base_url}，模型 {MODEL}。"
            f"请先运行 `ollama serve`，并用 `ollama pull {MODEL}` 拉取模型。"
        )
    if isinstance(error, APITimeoutError):
        return (
            f"LLM 调用超时：当前模型 {MODEL}，接口地址 {base_url}。"
            "请检查网络，或设置 DASHSCOPE_TIMEOUT=180。"
        )
    return f"LLM 调用失败: {error}"


def _is_retryable_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None and hasattr(error, "response"):
        status_code = getattr(error.response, "status_code", None)
    return status_code in RETRYABLE_STATUS_CODES


def _chat_completion_with_retry(**kwargs):
    attempts = int(os.getenv("OPENAI_REQUEST_ATTEMPTS", "4"))
    delay = float(os.getenv("OPENAI_RETRY_BASE_DELAY", "2"))
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            return _get_client().chat.completions.create(**kwargs)
        except Exception as e:
            last_error = e
            if attempt >= attempts or not _is_retryable_error(e):
                raise
            time.sleep(delay)
            delay *= 2

    raise last_error  # pragma: no cover


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if LLM_PROVIDER == "dashscope" and not os.getenv("DASHSCOPE_API_KEY"):
            raise RuntimeError("请先设置 DASHSCOPE_API_KEY 环境变量后再运行 Function Calling 版 Agent")
        if LLM_PROVIDER == "openai" and not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("请先设置 OPENAI_API_KEY 环境变量后再运行 Function Calling 版 Agent")
        _client = OpenAI(**_client_options())
    return _client

FC_SYSTEM_PROMPT = """你是一个专业的A股金融分析助手。
规则：
- 调用 financial_indicator 或 stock_price 之前，必须先用 company_lookup 获取股票代码
- 数字计算必须使用 calculator 工具，不能心算
- Final Answer 必须引用具体数据来源
- 如果没有合适工具能回答，直接说明原因
"""


def run(
    question: str,
    max_steps: int = 10,
    history: list[dict[str, str]] | None = None,
) -> Generator[dict, None, None]:
    """
    执行 Function Calling 版 ReAct 循环，yield 每一步结构化结果

    格式与 react_manual.run() 保持一致，便于 evaluate.py 统一对比
    """
    from tools import TOOLS_MAP, TOOLS_SCHEMA

    messages = [{"role": "system", "content": FC_SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": question})

    for step in range(1, max_steps + 1):
        try:
            response = _chat_completion_with_retry(
                model=MODEL,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                temperature=0,
            )
        except Exception as e:
            yield {
                "step":   step,
                "type":   "error",
                "answer": _llm_error_message(e),
            }
            return
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
