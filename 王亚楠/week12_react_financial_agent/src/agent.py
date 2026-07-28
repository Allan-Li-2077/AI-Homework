"""
统一入口：切换手写版 / Function Calling 版 ReAct Agent

使用方式：
  python agent.py
  python agent.py --mode manual   --question "茅台2023年毛利率是多少？"
  python agent.py --mode fc       --question "五粮液近一年股价涨跌幅？"
  python agent.py --mode manual   --question "..." --max_steps 8
  python agent.py --mode manual   --chat               # 交互对话模式
  python agent.py --list-sessions                      # 列出所有会话
  python agent.py --clear-memory                       # 清空全部记忆

环境变量：
  DASHSCOPE_API_KEY  必填
  AGENT_MODEL        默认 qwen-max，可换 deepseek-v3 等
"""

import os
import sys
import json
import argparse
import logging

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

logging.basicConfig(level=logging.WARNING)

DEFAULT_QUESTION = "贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？"

# ── 终端颜色 ────────────────────────────────────────────────────────────────
C = {
    "thought": "\033[36m",
    "action":  "\033[33m",
    "obs":     "\033[32m",
    "final":   "\033[35m",
    "error":   "\033[31m",
    "dim":     "\033[90m",
    "bold":    "\033[1m",
    "reset":   "\033[0m",
}

def _c(color: str, text: str) -> str:
    return f"{C.get(color, '')}{text}{C['reset']}"


def _print_step(step_data: dict, mode: str):
    """打印单个 ReAct 步骤（复用 react_manual 的彩色风格）"""
    stype = step_data["type"]

    if stype == "action":
        step_label = "[Step {}]".format(step_data["step"])
        print("\n  " + _c("dim", step_label))
        if mode == "manual" and step_data.get("thought"):
            print("  " + _c("thought", "🧠 " + step_data["thought"][:120]))
        action_label = "🔧 " + step_data["action"]
        args_label = json.dumps(step_data.get("action_input", {}), ensure_ascii=False)
        print("  " + _c("action", action_label) + "  " + _c("dim", args_label))
        obs = str(step_data.get("observation", ""))[:200]
        print("  " + _c("obs", "👁  " + obs))

    elif stype == "final":
        print(f"\n  {_c('final', '✅ ' + step_data['answer'])}")

    elif stype in ("error", "max_steps"):
        print(f"  {_c('error', '⚠️  ' + step_data.get('answer', step_data.get('observation', '')))}")


def _interactive_chat(mode: str, memory, session_id: str, max_steps: int):
    """交互式对话循环"""
    from chat import ChatSession

    session = ChatSession(mode=mode, memory=memory, session_id=session_id)

    mode_label = "手写Prompt解析" if mode == "manual" else "Function Calling"
    print("\n" + _c("bold", "🧠 进入交互对话模式") + " " + _c("dim", "(" + mode_label + ")"))
    print(f"{_c('dim', '   会话ID:')} {session_id}")
    if memory is not None:
        stats = memory.get_stats()
        print(f"{_c('dim', '   记忆:')} {stats['facts_count']} 条事实, {stats['total_turns']} 段历史")
    print(f"{_c('dim', '   命令: /history 查看历史 | /clear 重置对话 | /memory 记忆统计 | /exit 退出')}")
    print()

    while True:
        try:
            raw = input(f"{_c('bold', '> ')}").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{_c('dim', '对话结束，记忆已保存')}")
            break

        if not raw:
            continue

        # ── 特殊命令 ──────────────────────────────────────────────────
        if raw in ("/exit", "/quit"):
            print(f"{_c('dim', '对话结束，记忆已保存')}")
            break

        if raw == "/clear":
            session.clear()
            print(f"{_c('dim', '对话已重置（记忆不受影响）')}")
            continue

        if raw == "/history":
            summary = session.get_summary()
            print(f"\n{_c('dim', summary)}\n")
            continue

        if raw == "/memory":
            if memory is not None:
                stats = memory.get_stats()
                mem_info = "记忆统计: {} 条事实, {} 个会话, {} 轮对话".format(
                    stats["facts_count"], stats["sessions_count"], stats["total_turns"])
                print("\n" + _c("dim", mem_info))
                facts = memory.all_facts()
                if facts:
                    print(_c('dim', '已记住的事实:'))
                    for key, entry in list(facts.items())[:10]:
                        if isinstance(entry, dict) and "values" in entry:
                            fact_info = "  - {}: {}".format(key, entry["values"][-1]["value"])
                            print(_c("dim", fact_info))
            else:
                print(f"{_c('dim', '记忆系统未启用')}")
            print()
            continue

        # ── 正常提问 ──────────────────────────────────────────────────
        try:
            for step_data in session.send(raw, max_steps=max_steps):
                _print_step(step_data, mode)
        except Exception as e:
            print(_c("error", "❌ 出错: " + str(e)))

        print()  # 轮次间空行


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReAct Financial Agent")
    parser.add_argument(
        "--mode", choices=["manual", "fc"], default="manual",
        help="manual=手写Prompt解析版  fc=Function Calling版",
    )
    parser.add_argument("--question",  default=DEFAULT_QUESTION)
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument("--no-memory", action="store_true", help="禁用记忆系统")
    parser.add_argument("--session-id", default="default", help="会话标识（用于记忆隔离）")
    parser.add_argument("--list-sessions", action="store_true", help="列出所有历史会话")
    parser.add_argument("--clear-memory", action="store_true", help="清空全部记忆数据")
    parser.add_argument("--chat", action="store_true", help="进入交互式多轮对话模式")
    args = parser.parse_args()

    # ── 记忆管理命令（不进入 Agent 循环） ─────────────────────────────────
    from memory import MemoryStore
    store = MemoryStore()

    if args.list_sessions:
        sessions = store.list_sessions()
        if sessions:
            print(f"\n{'='*50}")
            print(f"历史会话（共 {len(sessions)} 个）")
            print(f"{'='*50}")
            for s in sessions:
                print(f"  [{s['session_id']}] {s['turns']} 轮对话   "
                      f"更新: {s.get('updated_at','')[:19]}")
        else:
            print("暂无历史会话记录")
        stats = store.get_stats()
        print(f"\n事实库: {stats['facts_count']} 条")
        print(f"存储位置: {stats['memory_dir']}")
        sys.exit(0)

    if args.clear_memory:
        store.clear_all()
        print("全部记忆已清空")
        sys.exit(0)

    # ── 启动 Agent ─────────────────────────────────────────────────────────
    mem = None if args.no_memory else store

    if args.chat:
        # 交互对话模式
        if not args.question == DEFAULT_QUESTION:
            # 用户同时指定了 --chat 和 --question → 作为首轮问题
            print(f"{_c('dim', '首轮问题:')} {args.question}")
        _interactive_chat(args.mode, mem, args.session_id, args.max_steps)
    else:
        # 单次查询模式
        if args.mode == "manual":
            from react_manual import run_and_print
        else:
            from react_function_calling import run_and_print

        run_and_print(args.question, args.max_steps, memory=mem, session_id=args.session_id)
