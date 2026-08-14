"""
交互式 CLI：输入问题 → 主 agent ReAct（实时打印）→ 派发子 agent（并行，实时打印）→ 最终报告

用法：
  python src/cli.py            # 子 agent 并行执行（默认）
  python src/cli.py --serial   # 子 agent 串行执行（对比并行加速基线）
"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import agents
from agents import run_research, SUBAGENT_ROLES


def print_main_step(step: dict) -> None:
    """打印主 agent 的 ReAct 一步（pre 决策 / post observation / final 三态）。"""
    if step["action"] == "Final Answer":
        print(f"[主] {step['thought'] or ''} → 最终答案")
        return
    if step.get("observation") is None:
        # pre：工具执行前，展示决策
        print(f"[主] {step['thought'] or ''}")
        print(f"     Action: {step['action']}")
        print(f"     Input:  {str(step['action_input'])[:100]}")
    else:
        # post：工具执行完，展示 observation 摘要
        obs = step["observation"]
        print(f"     Observation: {obs[:200]}{'...' if len(obs) > 200 else ''}")


def run_one(question: str, serial: bool) -> dict:
    """跑一轮问答，实时打印全过程，返回结果 dict。"""
    print("\n" + "=" * 64)
    print(f"问题: {question}")
    print("=" * 64)

    sub_names = {}  # sid -> 角色名（dispatch 事件时填充）

    def on_main_step(step):
        print_main_step(step)

    def on_dispatch(info):
        print(f"\n>>> 派发 {len(info['subagent_ids'])} 个子调研员"
              f"（{'串行' if serial else '并行'}）")
        for sid, role, topic in zip(info["subagent_ids"], info["roles"], info["subtopics"]):
            name = SUBAGENT_ROLES.get(role, {}).get("name", role)
            sub_names[sid] = f"{name}"
            print(f"    {sid} [{name}] {topic}")
        print()

    def on_subagent_step(sid, step):
        tag = sub_names.get(sid, sid)
        if step["action"] == "Final Answer":
            print(f"[{tag}] {step['thought'] or ''} → 完成")
        elif step.get("observation") is None:
            print(f"[{tag}] {step['thought'] or ''}")
            print(f"     Action: {step['action']}({str(step['action_input'])[:60]})")
        else:
            obs = step["observation"]
            print(f"     Observation: {obs[:150]}{'...' if len(obs) > 150 else ''}")

    def on_subagent_done(sid, duration, topic):
        tag = sub_names.get(sid, sid)
        print(f"[{tag}] ✅ 完成 ({duration}s): {topic[:40]}")

    r = run_research(question, on_main_step=on_main_step,
                     on_subagent_step=on_subagent_step,
                     on_subagent_done=on_subagent_done,
                     on_dispatch=on_dispatch, serial=serial)

    print("\n" + "-" * 64)
    if r["parallel_stats"]:
        st = r["parallel_stats"][-1]
        print(f"并行统计: {st['n_subagents']} 个子调研员, wall-clock {st['wall_clock']}s"
              f"（串行需 {st['serial_sum']}s, 加速 {st['speedup']}×）")
    print("\n=== 最终报告 ===")
    print(r["final_answer"])
    print("=" * 64)
    return r


def main():
    parser = argparse.ArgumentParser(description="通用多 Agent 问答系统（CLI）")
    parser.add_argument("--serial", action="store_true",
                        help="子 agent 串行执行（对比并行加速基线）")
    parser.add_argument("question", nargs="*", help="直接传入问题（不传则进入交互模式）")
    args = parser.parse_args()

    if args.question:
        run_one(" ".join(args.question), serial=args.serial)
        return

    print("通用多 Agent 问答系统（输入问题回车，Ctrl+C 退出）")
    while True:
        try:
            q = input("\n你: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break
        if not q:
            continue
        if q.lower() in ("quit", "exit"):
            break
        try:
            run_one(q, serial=args.serial)
        except Exception as e:
            print(f"\n[错误] {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    main()
