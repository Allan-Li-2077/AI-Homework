"""
统一入口：切换手写版 / Function Calling 版 ReAct Agent

使用方式：
  python agent.py
  python agent.py --mode manual   --question "茅台2023年毛利率是多少？"
  python agent.py --mode fc       --question "五粮液近一年股价涨跌幅？"
  python agent.py --mode manual   --question "..." --max_steps 8

环境变量：
  DASHSCOPE_API_KEY  必填
  AGENT_MODEL        默认 qwen-max，可换 deepseek-v3 等
"""

import os
import argparse

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

DEFAULT_QUESTION = "贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReAct Financial Agent")
    parser.add_argument(
        "--mode", choices=["manual", "fc"], default="manual",
        help="manual=手写Prompt解析版  fc=Function Calling版",
    )
    parser.add_argument("--question",  default=DEFAULT_QUESTION)
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument(
        "--chat", action="store_true",
        help="交互式多轮对话模式，连续输入问题，exit/quit 退出",
    )
    args = parser.parse_args()

    if args.chat:
        # 交互式多轮对话模式
        if args.mode == "manual":
            from react_manual import run_and_print as agent_run, COLORS, _c
        else:
            from react_function_calling import run_and_print as agent_run, COLORS, _c

        messages = None
        print(f"\n{'='*60}")
        print(f"🧠 ReAct Financial Agent - 交互式多轮对话")
        print(f"模型: {os.getenv('AGENT_MODEL', 'qwen-max')}  模式: {args.mode}")
        print("输入问题开始对话，输入 exit/quit 退出")
        print(f"{'='*60}\n")

        while True:
            try:
                q = input(">>> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if q.lower() in ("exit", "quit", "q"):
                break
            if not q.strip():
                continue

            result = agent_run(q, max_steps=args.max_steps, messages=messages)
            if result is not None:
                messages = result
                char_count = sum(len(str(m.get("content", ""))) for m in messages)
                msg_count = len(messages)
                print(f"\n  📝 上下文: {msg_count} 条消息 / ~{char_count} 字符\n")
        print("再见！")
    else:
        if args.mode == "manual":
            from react_manual import run_and_print
        else:
            from react_function_calling import run_and_print

        run_and_print(args.question, args.max_steps)
