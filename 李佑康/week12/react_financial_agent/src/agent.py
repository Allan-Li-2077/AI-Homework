"""单一入口：多轮对话。"""

import os
import argparse

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReAct Financial Agent")
    parser.add_argument("--question", default=None, help="单轮提问；不传则进入交互式多轮对话")
    parser.add_argument("--chat", action="store_true", help="强制进入交互式多轮对话")
    args = parser.parse_args()

    from react_manual import interactive_chat, run_and_print

    if args.chat or args.question is None:
        interactive_chat()
    else:
        run_and_print(args.question)
