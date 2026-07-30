"""
手写 Prompt 解析版 ReAct Agent

教学重点：
  1. ReAct 核心循环：Thought → Action → Observation，逐步推理
  2. System Prompt 约束输出格式，Python 正则解析每一步
  3. 对话历史拼接方式：每轮结果追加到 prompt，形成上下文记忆
  4. 停止条件：模型输出 Final Answer 或达到最大步数
  5. 多轮对话：支持传入对话历史，保持上下文连续性

使用方式：
  python react_manual.py
  python react_manual.py --question "Transformer的注意力机制是什么？"
  python react_manual.py --question "..." --max_steps 8 --verbose

依赖：
  pip install openai faiss-cpu sentence-transformers
  export DASHSCOPE_API_KEY="sk-xxx"
"""

import os
import re
import json
import time
import logging
import argparse
from typing import Generator, List, Dict

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
SYSTEM_PROMPT = """你是一个专业的AI技术问答助手，可以使用以下工具来回答问题：

工具列表：
1. rag_search(query) - 在AI技术论文库中语义检索（算法原理/实验结果/技术细节等）
2. ai_concept_lookup(name) - 查询AI概念基本信息（架构/模型/技术等）
3. calculator(expr) - 计算数学表达式（支持四则运算和math函数）
4. paper_summary(title) - 检索论文摘要信息
5. concept_compare(concept1, concept2) - 对比两个AI概念的异同

你必须严格按照以下格式交替输出，每次只能调用一个工具：

Thought: 分析当前状态，决定下一步做什么
Action: 工具名称
Action Input: {"参数名": "参数值"}

收到工具结果后继续推理，直到可以给出最终答案：

Thought: 已有足够信息
Final Answer: 完整的回答（含数据来源）

规则：
- 如果需要了解概念定义，先用 ai_concept_lookup 查询
- 如果需要论文具体内容，使用 rag_search 检索
- 如果需要论文摘要，使用 paper_summary
- 如果需要对比两个概念，使用 concept_compare
- 数字计算必须用 calculator，不能心算
- Final Answer 必须引用具体数据来源（哪篇论文哪一页）
- 如果没有合适工具能回答，直接输出 Final Answer 说明原因
- 注意结合对话历史中的上下文信息回答问题
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

def run(
    question: str,
    max_steps: int = 10,
    verbose: bool = True,
    conversation_history: List[Dict[str, str]] = None,
) -> Generator[dict, None, None]:
    """
    执行 ReAct 循环，yield 每一步的结构化结果

    每个 yield 的 dict 格式：
      {"step": int, "thought": str, "action": str, "action_input": dict, "observation": str}
    最后一个 yield：
      {"step": int, "thought": str, "type": "final", "answer": str}

    参数：
      question: 当前问题
      max_steps: 最大步数
      verbose: 详细日志
      conversation_history: 对话历史，格式为 [{"question": "...", "answer": "..."}, ...]
    """
    from tools import TOOLS_MAP

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    if conversation_history:
        for turn in conversation_history:
            messages.append({"role": "user",   "content": turn["question"]})
            messages.append({"role": "assistant", "content": turn["answer"]})

    messages.append({"role": "user", "content": question})

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

        messages.append({"role": "assistant", "content": llm_output})
        messages.append({
            "role":    "user",
            "content": f"Observation: {observation}\n",
        })

    yield {
        "step":   max_steps + 1,
        "type":   "max_steps",
        "answer": f"已达最大步数 {max_steps}，未能得出最终答案",
    }


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
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    print(f"模型: {MODEL}  实现: 手写Prompt解析")
    print('='*60)

    start = time.time()
    step_count = 0

    for step_data in run(question, max_steps=max_steps):
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
    parser.add_argument("--question",  default="Transformer和RNN的主要区别是什么？")
    parser.add_argument("--max_steps", type=int, default=10)
    args = parser.parse_args()
    run_and_print(args.question, args.max_steps)