"""
Parallel vs Serial 量化对比（凸显 subagent 并行优势）

教学重点：
  同一组审查问题，主 agent 派发的子审查员分别用「并行(ThreadPool)」和
  「串行(for 循环)」两种方式执行，对比 wall-clock，量化并行加速。

  并行的意义不是少做事，而是把 N 个独立维度任务的墙钟时间从 sum 压到 max。
  本项目的 dispatch_reviewers 用 ThreadPoolExecutor 实现并行，
  serial=True 时退化为串行（eval 基线）。

使用方式：
  python src/eval_compare.py                # 默认 3 题，parallel vs serial
  python src/eval_compare.py --limit 1      # 快速版（单题）
  python src/eval_compare.py --project /path/to/repo  # 审查指定项目
"""
import os
import sys
import time
import json
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

EVAL_QUESTIONS = [
    "请审查这个项目的代码质量：安全、性能、代码风格",
    "请审查这个项目的代码质量：逻辑错误、架构设计",
    "请审查这个项目的代码质量：安全、性能、风格、逻辑、架构（全部维度）",
]


def run_one(question: str, serial: bool) -> dict:
    """跑一次审查，返回统计信息。
    serial=True/False 控制子审查员执行方式。"""
    import agents
    t0 = time.time()
    r = agents.run_review(question, serial=serial)
    wall = time.time() - t0
    ps = r["parallel_stats"][-1] if r["parallel_stats"] else None
    return {
        "wall": round(wall, 2),
        "n_subagents": ps["n_subagents"] if ps else 0,
        "dispatch_wall": ps["wall_clock"] if ps else 0,
        "serial_sum": ps["serial_sum"] if ps else 0,
        "speedup": ps["speedup"] if ps else 0,
        "dispatched": len(r["dispatches"]) > 0,
    }


def main():
    parser = argparse.ArgumentParser(description="parallel vs serial 代码审查对比")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--project", type=str, default="")
    args = parser.parse_args()

    if args.project:
        os.environ["PROJECT_ROOT"] = args.project

    qs = EVAL_QUESTIONS[:args.limit] if args.limit else EVAL_QUESTIONS

    results = []
    for i, q in enumerate(qs):
        logger.warning(f"[{i + 1}/{len(qs)}] {q[:40]}...")
        p = run_one(q, serial=False)
        s = run_one(q, serial=True)
        results.append({"question": q, "parallel": p, "serial": s})
        print(f"  {q[:30]:<32} 并行 {p['wall']}s vs 串行 {s['wall']}s "
              f"(审查员 {p['n_subagents']}, 加速 {p['speedup']}×)")

    avg_p = sum(r["parallel"]["wall"] for r in results) / len(results)
    avg_s = sum(r["serial"]["wall"] for r in results) / len(results)
    avg_spd = sum(r["parallel"]["speedup"] for r in results) / len(results)

    print(f"\n{'=' * 60}")
    print(f"Parallel vs Serial 对比（{len(results)} 题）")
    print(f"{'=' * 60}")
    print(f"{'指标':<16} {'并行(ThreadPool)':<18} {'串行(for循环)':<18}")
    print(f"{'平均墙钟(s)':<16} {avg_p:<18.2f} {avg_s:<18.2f}")
    print(f"{'平均加速':<16} {avg_spd:<18.2f}× {'—':<18}")
    print(f"\n结论：subagent 并行把 N 个独立维度审查的墙钟从 sum 压到 ≈max，"
          f"平均加速 {avg_spd:.2f}×")

    out = {
        "summary": {
            "avg_parallel_s": round(avg_p, 2),
            "avg_serial_s": round(avg_s, 2),
            "avg_speedup": round(avg_spd, 2),
        },
        "details": results,
    }
    out_dir = Path(__file__).parent.parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "eval_compare.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n结果已保存: {out_dir / 'eval_compare.json'}")


if __name__ == "__main__":
    main()
