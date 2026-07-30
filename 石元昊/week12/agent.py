"""
统一入口：多轮对话版 ReAct Financial Agent

使用方式：
  python agent.py                           # 交互式多轮对话（默认手写版）
  python agent.py --mode fc                 # 交互式多轮对话（Function Calling 版）
  python agent.py --mode manual --question "茅台2023年毛利率是多少？"  # 单轮模式
  python agent.py --mode fc --question "五粮液近一年股价涨跌幅？"

多轮对话示例：
  用户: 贵州茅台2023年的毛利率是多少？
  助手: ...（调用工具后回答）
  用户: 那五粮液呢？                  ← 可省略主语，模型结合上下文理解
  助手: ...
  用户: 两者差多少？                  ← 继续追问
  助手: ...
  用户: /history                      ← 查看对话摘要
  用户: /clear                        ← 清空历史重新开始
  用户: /quit                         ← 退出
"""

import os
import argparse

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

DEFAULT_QUESTION = "贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReAct Financial Agent（多轮对话版）")
    parser.add_argument(
        "--mode", choices=["manual", "fc"], default="manual",
        help="manual=手写Prompt解析版  fc=Function Calling版",
    )
    parser.add_argument(
        "--question", default=None,
        help="指定问题（单轮模式）；不指定则进入交互式多轮对话",
    )
    parser.add_argument("--max_steps", type=int, default=10)
    args = parser.parse_args()

    if args.mode == "manual":
        from react_manual import run_and_print, run_interactive
    else:
        from react_function_calling import run_and_print, run_interactive

    if args.question:
        run_and_print(args.question, args.max_steps)
    else:
        run_interactive(args.max_steps)
