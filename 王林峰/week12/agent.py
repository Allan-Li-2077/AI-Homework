"""
统一入口：切换手写版 / Function Calling 版 ReAct Agent
使用方式：
  python agent.py
  python agent.py --mode manual   --question "茅台2023年毛利率是多少？" --session-id s1001
  python agent.py --mode fc       --question "五粮液近一年股价涨跌幅？" --session-id s1001
  python agent.py --mode manual   --question "..." --max_steps 8 --session-id s1002
环境变量：
  DASHSCOPE_API_KEY  必填
  AGENT_MODEL        默认 qwen-max，可换 deepseek-v3 等
"""
import os
import argparse
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
DEFAULT_QUESTION = "贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？"
DEFAULT_SESSION_ID = "default_single_session"
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReAct Financial Agent 支持多轮对话")
    parser.add_argument(
        "--mode", choices=["manual", "fc"], default="manual",
        help="manual=手写Prompt解析版  fc=Function Calling版",
    )
    parser.add_argument("--question",  default=DEFAULT_QUESTION)
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID, help="多轮对话会话标识，不同ID隔离上下文")
    args = parser.parse_args()
    if args.mode == "manual":
        from react_manual import run_and_print
    else:
        from react_function_calling import run_and_print
    # 传递session_id实现多轮记忆
    run_and_print(args.question, args.max_steps, args.session_id)