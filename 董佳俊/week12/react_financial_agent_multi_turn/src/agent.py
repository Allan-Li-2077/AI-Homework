"""
统一入口：切换手写版 / Function Calling 版 ReAct Agent，支持多轮交互模式

使用方式：
  # 单轮模式
  python agent.py --mode manual --question "茅台2023年毛利率是多少？"
  python agent.py --mode fc     --question "五粮液近一年股价涨跌幅？"
  python agent.py --mode manual --question "..." --max_steps 8

  # 多轮交互模式
  python agent.py --mode manual --interactive
  python agent.py --mode fc     --interactive

环境变量：
  DASHSCOPE_API_KEY  必填
  AGENT_MODEL        默认 qwen-max，可换 deepseek-v3 等
"""

import os
import sys
import json
import time
import argparse

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# 确保可以 import 同目录的 react_* 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_QUESTION = "贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？"

# ── 彩色输出（复用 react_manual 的风格）───────────────────────────────────────

COLORS = {
    "thought":  "\033[36m",
    "action":   "\033[33m",
    "obs":      "\033[32m",
    "final":    "\033[35m",
    "error":    "\033[31m",
    "info":     "\033[37m",
    "reset":    "\033[0m",
}

def _c(color: str, text: str) -> str:
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def _display_step(step_data: dict, mode: str):
    """打印单步推理结果"""
    stype = step_data["type"]

    if stype == "session_messages":
        return   # 内部使用，不显示

    if stype == "action":
        print(f"\n[Step {step_data['step']}]")
        if mode == "manual" and step_data.get("thought"):
            print(_c("thought", f"🧠 Thought: {step_data['thought']}"))
        elif mode == "fc":
            print(_c("thought", "🧠 Thought: （模型内部推理，Function Calling 版不可见）"))
        print(_c("action",  f"🔧 Action:  {step_data['action']}"))
        print(_c("action",  f"   Input:   {json.dumps(step_data['action_input'], ensure_ascii=False)}"))
        print(_c("obs",     f"👁  Obs:     {step_data['observation'][:300]}"))

    elif stype == "final":
        if step_data.get("thought"):
            print(_c("thought", f"\n🧠 Thought: {step_data['thought']}"))
        print(_c("final",  f"\n✅ Final Answer:\n{step_data['answer']}"))

    elif stype in ("error", "max_steps"):
        print(_c("error", f"\n⚠️  {step_data.get('answer', step_data.get('observation', ''))}"))


def _run_single(mode: str, question: str, max_steps: int, messages: list | None):
    """执行一次推理并打印，返回更新后的 messages 列表"""
    if mode == "manual":
        from react_manual import run
    else:
        from react_function_calling import run

    start = time.time()
    step_count = 0

    for step_data in run(question, max_steps=max_steps, messages=messages):
        stype = step_data["type"]

        if stype == "session_messages":
            messages = step_data["messages"]
            continue

        step_count += 1
        _display_step(step_data, mode)

        if stype == "final":
            elapsed = time.time() - start
            print(f"\n共 {step_data['step']} 步，耗时 {elapsed:.1f}s")

    return messages


def _interactive_loop(mode: str, max_steps: int):
    """多轮交互 REPL 循环"""
    model = os.getenv("AGENT_MODEL", "qwen-max" if mode == "manual" else "deepseek-v4-flash")
    impl = "手写Prompt解析" if mode == "manual" else "Function Calling"

    print(f"\n{'='*60}")
    print(f"  ReAct Financial Agent - 交互模式")
    print(f"  模型: {model}    实现: {impl}")
    print(f"  /clear  清空对话历史")
    print(f"  /history  查看当前对话轮数")
    print(f"  exit / quit  退出")
    print(f"{'='*60}")

    messages = None
    turn = 0

    while True:
        try:
            question = input(f"\n[{turn+1}] >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not question:
            continue
        if question.lower() in ("exit", "quit"):
            print("再见！")
            break
        if question == "/clear":
            messages = None
            turn = 0
            print(_c("info", "(对话历史已清空)"))
            continue
        if question == "/history":
            if messages is None:
                print(f"当前对话轮数: 0")
            else:
                # 统计 user 消息数来估算轮次
                user_count = sum(1 for m in messages if m.get("role") == "user")
                print(f"当前对话轮数: {user_count}")
            continue

        turn += 1
        messages = _run_single(mode, question, max_steps, messages)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReAct Financial Agent (Multi-Turn)")
    parser.add_argument(
        "--mode", choices=["manual", "fc"], default="manual",
        help="manual=手写Prompt解析版  fc=Function Calling版",
    )
    parser.add_argument("--question",    default=None)
    parser.add_argument("--max_steps",   type=int, default=10)
    parser.add_argument("--interactive", action="store_true",
                        help="交互模式：保持对话历史，支持多轮提问")
    args = parser.parse_args()

    if args.interactive:
        _interactive_loop(args.mode, args.max_steps)
    else:
        # 单轮模式（向后兼容）
        question = args.question or DEFAULT_QUESTION
        if args.mode == "manual":
            from react_manual import run_and_print
        else:
            from react_function_calling import run_and_print
        run_and_print(question, args.max_steps)
