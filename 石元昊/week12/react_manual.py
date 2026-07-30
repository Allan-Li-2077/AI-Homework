"""
手写 Prompt 解析版 ReAct Agent —— 多轮对话版

教学重点：
  1. 在原版单轮 ReAct 基础上，增加 ChatSession 管理跨轮对话历史
  2. 每轮问答结束后，将 user 问题 + assistant 最终答案追加到 messages，
     使后续提问能感知前文上下文（如"那五粮液呢？"可省略主语）
  3. ReAct 内部推理步骤（Thought/Action/Observation）仍为单轮内临时消息，
     不污染跨轮历史，保持上下文窗口干净
  4. 支持 /clear 清空历史、/history 查看对话摘要、/quit 退出

使用方式：
  python react_manual.py                       # 进入交互式多轮对话
  python react_manual.py --question "..."      # 单轮模式（兼容原版）

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
from typing import Generator

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
- 注意对话历史中的上下文，用户可能会追问或省略主语，请结合前文理解
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


# ── ReAct 核心循环（多轮对话版） ───────────────────────────────────────────────

def run(
    question: str,
    messages: list[dict],
    max_steps: int = 10,
    verbose: bool = True,
) -> Generator[dict, None, None]:
    """
    执行一轮 ReAct 循环，yield 每一步的结构化结果。

    与原版区别：
      - messages 由外部传入并在多轮间共享，而非每次新建
      - 函数内部只追加本轮的推理中间消息，最终答案由调用方统一追加

    每个 yield 的 dict 格式同原版：
      {"step": int, "type": "action"|"final"|"error"|"max_steps", ...}
    """
    from tools import TOOLS_MAP

    # 本轮用户输入
    messages.append({"role": "user", "content": question})

    # 记录本轮开始时的消息长度，用于推理中间消息的回滚管理
    # （ReAct 中间步骤不应泄露到下一轮）
    react_start_len = len(messages)

    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0,
            stop=["Observation:"],
        )
        llm_output = response.choices[0].message.content.strip()
        parsed = _parse_step(llm_output)

        if parsed["type"] == "final":
            # 清理本轮 ReAct 中间消息，只保留 user 问题
            del messages[react_start_len:]
            # 将最终答案作为 assistant 消息追加，供下轮感知
            messages.append({"role": "assistant", "content": parsed["answer"]})
            yield {
                "step":    step,
                "type":    "final",
                "thought": parsed["thought"],
                "answer":  parsed["answer"],
            }
            return

        if parsed["type"] == "unparseable":
            del messages[react_start_len:]
            messages.append({"role": "assistant", "content": f"（解析失败）{llm_output[:200]}"})
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

        # 将本步结果追加到对话历史（仅本轮 ReAct 内可见）
        messages.append({"role": "assistant", "content": llm_output})
        messages.append({
            "role":    "user",
            "content": f"Observation: {observation}\n",
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
    管理多轮对话的 messages 列表。

    设计要点：
      - messages[0] 固定为 system prompt
      - 每轮 ReAct 的中间推理步骤在回答完成后被清理，
        只保留 user 问题 + assistant 最终答案，避免上下文膨胀
      - 支持 /clear 重置历史、/history 查看摘要
    """

    def __init__(self, max_steps: int = 10):
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.max_steps = max_steps
        self.turn_count = 0

    def ask(self, question: str) -> Generator[dict, None, None]:
        """发起一轮提问，yield ReAct 每一步结果"""
        self.turn_count += 1
        yield from run(question, self.messages, max_steps=self.max_steps)

    def clear(self):
        """清空对话历史，仅保留 system prompt"""
        self.messages = [self.messages[0]]
        self.turn_count = 0

    def history_summary(self) -> str:
        """返回对话历史摘要（仅 user/assistant 轮次）"""
        lines = []
        turn = 0
        for msg in self.messages:
            if msg["role"] == "user" and not msg["content"].startswith("Observation:"):
                turn += 1
                lines.append(f"[轮次 {turn}] 用户: {msg['content'][:80]}")
            elif msg["role"] == "assistant" and not msg["content"].startswith("Thought:"):
                lines.append(f"       助手: {msg['content'][:80]}")
        return "\n".join(lines) if lines else "（暂无对话历史）"


# ── CLI 打印 ──────────────────────────────────────────────────────────────────

COLORS = {
    "thought":  "\033[36m",
    "action":   "\033[33m",
    "obs":      "\033[32m",
    "final":    "\033[35m",
    "error":    "\033[31m",
    "reset":    "\033[0m",
}

def _c(color: str, text: str) -> str:
    return f"{COLORS[color]}{text}{COLORS['reset']}"


def run_and_print(question: str, max_steps: int = 10):
    """单轮兼容接口（与原版行为一致）"""
    session = ChatSession(max_steps=max_steps)
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    print(f"模型: {MODEL}  实现: 手写Prompt解析（多轮版）")
    print('='*60)

    start = time.time()
    for step_data in session.ask(question):
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


def run_interactive(max_steps: int = 10):
    """交互式多轮对话入口"""
    session = ChatSession(max_steps=max_steps)

    print(f"\n{'='*60}")
    print(f"🤖 A股金融分析助手（多轮对话模式）")
    print(f"   模型: {MODEL}  实现: 手写Prompt解析")
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
    parser.add_argument("--question",  default=None, help="指定问题（单轮模式）；不指定则进入交互式多轮对话")
    parser.add_argument("--max_steps", type=int, default=10)
    args = parser.parse_args()

    if args.question:
        run_and_print(args.question, args.max_steps)
    else:
        run_interactive(args.max_steps)
