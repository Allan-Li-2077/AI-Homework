"""
交互式 CLI 模式 — 不依赖 FastAPI，命令行直接调研

用法：
  python src/cli.py                    # 交互式，输入问题回车即调研
  python src/cli.py --question "xxx"   # 单次调研
  python src/cli.py --serial           # 串行模式（对比并行加速用）

实时打印主 agent + 各 subagent 的 ReAct 步骤，最终输出报告 + 并行统计。
"""

import sys, time, argparse, logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agents import run_research


# ── 颜色输出（Windows 终端兼容）──────────────────────────────────────────────
def _c(text, code):
    return f"\033[{code}m{text}\033[0m"

def bold(t): return _c(t, "1")
def dim(t): return _c(t, "2")
def cyan(t): return _c(t, "36")
def green(t): return _c(t, "32")
def yellow(t): return _c(t, "33")
def magenta(t): return _c(t, "35")


# ── 回调：实时打印步骤 ────────────────────────────────────────────────────────

def make_print_callbacks():
    """构造回调函数集，实时打印 ReAct 步骤到终端。"""

    def on_main_step(step):
        agent = cyan("[主agent]")
        if step.get("final"):
            print(f"\n  {agent} {green('Final Answer')} (共 {step['idx']+1} 步)")
        else:
            thought = (step.get("thought") or "")[:80]
            action = step.get("action", "")
            inp = (step.get("action_input") or "")[:60]
            obs = step.get("observation")
            if obs is None:
                # pre-execution: 刚决定做什么
                print(f"\n  {agent} Step {step['idx']}: {yellow(action)}({dim(inp)})")
                if thought:
                    print(f"         Thought: {dim(thought)}")
            else:
                # post-execution: 拿到结果
                obs_preview = (obs or "")[:120].replace("\n", " ")
                print(f"         → {dim(obs_preview)}")

    def on_dispatch(info):
        topics = info.get("subtopics", [])
        ids = info.get("subagent_ids", [])
        print(f"\n  {magenta('>>> 派发')} {len(topics)} 个子调研员并行:")
        for t, sid in zip(topics, ids):
            print(f"      {sid}: {t}")

    def on_subagent_step(sid, step):
        tag = magenta(f"[{sid}]")
        if step.get("final"):
            print(f"  {tag} {green('完成')}")
        else:
            action = step.get("action", "")
            inp = (step.get("action_input") or "")[:50]
            obs = step.get("observation")
            if obs is None:
                print(f"  {tag} {action}({dim(inp)})")
            else:
                obs_preview = (obs or "")[:80].replace("\n", " ")
                print(f"       → {dim(obs_preview)}")

    def on_subagent_done(sid, duration, topic):
        print(f"  {magenta(sid)} {green('done')} {duration}s — {topic[:40]}")

    return {
        "on_main_step": on_main_step,
        "on_dispatch": on_dispatch,
        "on_subagent_step": on_subagent_step,
        "on_subagent_done": on_subagent_done,
    }


# ── 主循环 ────────────────────────────────────────────────────────────────────

def run_once(question: str, serial: bool = False):
    """执行一次调研，实时打印步骤。"""
    cbs = make_print_callbacks()
    print(f"\n{'='*60}")
    print(f"  问题: {bold(question)}")
    print(f"  模式: {'串行' if serial else '并行(ThreadPool)'}")
    print(f"{'='*60}")

    t0 = time.time()
    r = run_research(question, serial=serial, **cbs)
    wall = time.time() - t0

    # 打印报告
    print(f"\n{'─'*60}")
    print(bold("  最终报告"))
    print(f"{'─'*60}")
    print(r["final_answer"])

    # 打印统计
    print(f"\n{'─'*60}")
    print(bold("  统计"))
    print(f"{'─'*60}")
    print(f"  总耗时: {wall:.1f}s")
    print(f"  主 agent 步数: {len(r['main_trace'])}")
    print(f"  subagent 数: {len(r['subagents'])}")
    if r["parallel_stats"]:
        ps = r["parallel_stats"][-1]
        print(f"  dispatch 加速: {ps['speedup']}×  (并行 {ps['wall_clock']}s vs 串行 {ps['serial_sum']}s)")
    print()


def main():
    parser = argparse.ArgumentParser(description="Subagent 并行调研 CLI")
    parser.add_argument("--question", "-q", type=str, help="单次调研问题（省略则交互式）")
    parser.add_argument("--serial", action="store_true", help="串行模式（对比用）")
    args = parser.parse_args()

    # 降低底层日志噪音
    logging.basicConfig(level=logging.WARNING)

    if args.question:
        run_once(args.question, serial=args.serial)
        return

    # 交互式模式
    print(bold("  Subagent 并行调研系统 — CLI 模式"))
    print(dim("  输入调研问题回车执行，输入 q 退出\n"))

    while True:
        try:
            question = input(bold("问题> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break
        if not question or question.lower() in ("q", "quit", "exit"):
            print("再见!")
            break
        run_once(question, serial=args.serial)


if __name__ == "__main__":
    main()
