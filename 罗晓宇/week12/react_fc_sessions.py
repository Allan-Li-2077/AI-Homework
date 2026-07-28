"""
Function Calling API 版 ReAct Agent

修改重点：
    - 增加session内记忆功能，修改成多轮对话模式

修改方式：
  1、增加session_id参数，传入同一个session_id即可在同一会话中记忆上下文
  2、外部调用时，需要传入session_id参数，才能继续之前的对话
  3、如果session_id不存在或不传入session_id参数，会创建一个新的会话
  4、session会话会持续存在，直到外部调用结束或超时
  5、每个会话的上下文是独立的，不会与其他会话共享
  6、会话上限个数为10个，超过后会自动删除旧的会话
  7、history会话上下文中只保存问题和最终答案，不保存中间步骤的Thought和Action
  8、history存放在本地文件夹historystore中，文件名格式为 session_id.jsonl

  python react_fc_loop.py
  python react_fc_loop.py --question "茅台近一年股价涨跌幅如何？"
  python react_fc_loop.py --question "..." --max_steps 8 --session_id "123456"

  依赖：
  pip install openai faiss-cpu sentence-transformers akshare
  export DEEPSEEK_API_KEY="sk-xxx"
"""

import os
import json
import time
import logging
import argparse

from pathlib import Path

from typing import Generator

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

# 项目根目录
CUR_DIR        = Path(__file__).parent.parent
HISTORY_DIR = CUR_DIR / "historystore"
MAX_SESSIONS = 10


def run(question: str, max_steps: int = 10, history: list[dict] | None = None) -> Generator[dict, None, None]:
    """
    执行 Function Calling 版 ReAct 循环，yield 每一步结构化结果

    history: 可选的多轮会话消息列表，已按照标准 role/content 格式排列
    """
    from tools import TOOLS_MAP, TOOLS_SCHEMA

    messages = [{"role": "system", "content": FC_SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
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
                    observation = tool_fn(**tool_args) # 调用工具函数
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

def _ensure_history_dir():
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _touch_session_file(session_id: str):
    session_path = HISTORY_DIR / f"{session_id}.jsonl"
    if session_path.exists():
        os.utime(session_path, None)


def _append_session_history(session_id: str, question: str, answer: str) -> None:
    _ensure_history_dir()
    _evict_old_sessions()
    session_path = HISTORY_DIR / f"{session_id}.jsonl"
    with open(session_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"question": question, "answer": answer}, ensure_ascii=False) + "\n")
    _touch_session_file(session_id)


def _evict_old_sessions():
    """
    删除超过 MAX_SESSIONS 的旧会话文件
    """
    if not HISTORY_DIR.exists():
        return

    session_files = sorted(HISTORY_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
    while len(session_files) > MAX_SESSIONS:
        old_file = session_files.pop(0)
        old_file.unlink()
        logger.info(f"已删除旧会话文件: {old_file.name}")

def load_history(session_id: str) -> list[dict]:
    """
    从本地文件夹historystore中加载会话上下文history

    返回标准 chat message 列表：user/assistant 交替消息。
    """
    history: list[dict] = []
    session_path = HISTORY_DIR / f"{session_id}.jsonl"
    if session_path.exists():
        with open(session_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                history.append({"role": "user", "content": item.get("question", "")})
                history.append({"role": "assistant", "content": item.get("answer", "")})
        _touch_session_file(session_id)

    return history

def run_and_print(question: str, max_steps: int = 10, session_id: str = None):
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    print(f"模型: {MODEL}  实现: Function Calling")
    print('='*60)

    history = []
    if session_id is not None:
        history = load_history(session_id)
        print(f"会话ID: {session_id} (继续上次会话)")
    else:
        # 没有会话id，则创建一个新的会话id
        session_id = str(int(time.time() * 1000))[-6:]  # 使用时间戳的后6位作为会话id
        print(f"新会话ID: {session_id}，请在下一轮继续使用 --session_id {session_id}")

    start = time.time()

    for step_data in run(question, max_steps=max_steps, history=history):
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

            # 将本次问答写入会话历史文件
            if session_id is not None:
                _append_session_history(session_id, question, step_data['answer'])

            print(f"\n{'─'*60}")
            print(_c("final", f"\n✅ Final Answer:\n{step_data['answer']}"))
            print(f"\n共 {step_data['step']} 步，耗时 {elapsed:.1f}s")
            print(f"会话ID: {session_id}")

        elif stype in ("error", "max_steps"):
            print(_c("error", f"\n⚠️  {step_data.get('answer', '')}"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--question",  default="贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？")
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument("--session_id",  default=None)
    args = parser.parse_args()
    run_and_print(args.question, args.max_steps, args.session_id)
