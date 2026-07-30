"""
统一入口：切换手写版 / Function Calling 版 ReAct Agent

使用方式：
  # 单次查询
  python agent.py
  python agent.py --mode manual   --question "茅台2023年毛利率是多少？"
  python agent.py --mode fc       --question "五粮液近一年股价涨跌幅？"

  # 多轮对话（交互式）
  python agent.py --chat
  python agent.py --mode fc --chat

环境变量：
  DASHSCOPE_API_KEY  必填
  AGENT_MODEL        默认 qwen-max，可换 deepseek-v3 等
"""

import os
import sys
import argparse

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

DEFAULT_QUESTION = "贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？"


def run_chat(mode: str, max_steps: int = 10):
    """
    交互式多轮对话模式。
    保持对话历史，支持连续追问。
    输入 /history 查看历史，/new 清空历史，exit/quit 退出。
    """
    if mode == "manual":
        from react_manual import run as react_run
    else:
        from react_function_calling import run as react_run

    conversation_history = []

    print(f"\n{'='*60}")
    print(f"💬 ReAct 多轮对话模式 ({'手写Prompt解析' if mode == 'manual' else 'Function Calling'})")
    print(f"模型: {os.getenv('AGENT_MODEL', 'qwen-max')}")
    print(f"输入 exit/quit 退出，/new 清空历史，/history 查看历史")
    print(f"{'='*60}\n")

    while True:
        try:
            question = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not question:
            continue
        if question.lower() in ("exit", "quit"):
            print("再见！")
            break
        if question == "/new":
            conversation_history = []
            print("已清空对话历史。\n")
            continue
        if question == "/history":
            if not conversation_history:
                print("（暂无对话历史）\n")
            else:
                print(f"\n--- 对话历史 ({len(conversation_history)//2} 轮) ---")
                for msg in conversation_history:
                    role = "你" if msg["role"] == "user" else "助手"
                    print(f"[{role}] {msg['content'][:200]}")
                print("--- 历史结束 ---\n")
            continue

        # 执行 ReAct 循环
        print(f"\n助手: （思考中...）\n")

        final_answer = None
        for step_data in react_run(question, max_steps=max_steps, conversation_history=conversation_history):
            if step_data["type"] == "action":
                print(f"  [Step {step_data['step']}] {step_data['action']}({step_data['action_input']})")
            elif step_data["type"] == "final":
                final_answer = step_data["answer"]
                print(f"\n✅ {final_answer}\n")

        if final_answer is None:
            print("⚠️  未能得出答案。\n")
        else:
            # 保存到对话历史
            conversation_history.append({"role": "user", "content": question})
            conversation_history.append({"role": "assistant", "content": final_answer})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReAct Financial Agent")
    parser.add_argument(
        "--mode", choices=["manual", "fc"], default="manual",
        help="manual=手写Prompt解析版  fc=Function Calling版",
    )
    parser.add_argument("--question",  default=None, help="单次查询问题（如不传则使用默认问题）")
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument("--chat",      action="store_true", help="交互式多轮对话模式")
    args = parser.parse_args()

    if args.chat:
        run_chat(args.mode, args.max_steps)
    else:
        if args.mode == "manual":
            from react_manual import run_and_print
        else:
            from react_function_calling import run_and_print

        run_and_print(args.question or DEFAULT_QUESTION, args.max_steps)
