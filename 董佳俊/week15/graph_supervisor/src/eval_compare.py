"""
Parallel vs Serial 量化对比（凸显 subagent 并行优势）

教学重点：
  同一组任务，同一张图分别用「并行(ThreadPool)」和「串行(for 循环)」执行，
  对比墙钟，量化并行收益。并行的意义不是少做事，而是把 N 个独立子任务的
  墙钟从 sum 压到 max。

  三道题特意设计成三种形态：
  1. 三 worker 复合（research+data 并行 → writer 依赖）——看 fan-out 加速与端到端加速的差距（Amdahl）
  2. 双 worker 全并行（research+data 无依赖）——fan-out 收益最高的一题
  3. 纯依赖链（researcher → writer）——fan-out 段只有 1 个节点，
     端到端加速 ≈1.0，正面对照教程 P21「纯顺序任务，图反而降性能」

使用方式：
  python eval_compare.py            # 默认 3 题，每题 parallel + serial 各跑一次
  python eval_compare.py --limit 2  # 快速版
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.WARNING)

from graph import run_graph  # noqa: E402

EVAL_QUESTIONS = [
    # 1. 三 worker 复合：fan-out 段并行 + 依赖边 + writer 聚合
    "帮我调研一下中国咖啡市场现状，算一算近三年市场规模（2021年3817亿元、2022年4856亿元、"
    "2023年6188亿元）的年均增速，再写一篇 800 字左右的公众号推文，面向想开店创业的人",
    # 2. 双 worker 全并行：无依赖边，fan-out 收益最高
    "调研中国扫地机器人行业的市场规模与竞争格局；已知 2021-2023 年市场规模为 108/124/141 亿元，"
    "用工具计算同比增速和 CAGR",
    # 3. 反例：纯依赖链，无并行分支，端到端加速 ≈1
    "写一篇新能源汽车行业科普推文，先调研行业现状",
]


def run_one(question: str, serial: bool) -> dict:
    """跑一次完整图编排，返回量化指标。"""
    t0 = time.time()
    r = run_graph(question, serial=serial)
    wall = round(time.time() - t0, 2)
    stats = r["stats"]
    s0 = stats["stages"][0] if stats["stages"] else None
    return {
        "wall": wall,
        "task_type": r["plan"]["task_type"],
        "n_nodes": len(r["results"]),
        "fanout_wall": s0["wall_clock"] if s0 else 0.0,
        "fanout_serial": s0["serial_sum"] if s0 else 0.0,
        "fanout_speedup": s0["speedup"] if s0 else 0.0,
        "total_speedup": stats["total_speedup"],
    }


def main():
    parser = argparse.ArgumentParser(description="parallel vs serial 对比")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题")
    args = parser.parse_args()
    qs = EVAL_QUESTIONS[:args.limit] if args.limit else EVAL_QUESTIONS

    results = []
    for i, q in enumerate(qs):
        print(f"[{i+1}/{len(qs)}] {q[:24]}…")
        p = run_one(q, serial=False)
        s = run_one(q, serial=True)
        results.append({"question": q, "parallel": p, "serial": s})
        print(f"  并行 {p['wall']}s (fan-out 加速 {p['fanout_speedup']}x) "
              f"vs 串行 {s['wall']}s → 端到端 {s['wall'] / p['wall']:.2f}x\n")

    avg_p = sum(r["parallel"]["wall"] for r in results) / len(results)
    avg_s = sum(r["serial"]["wall"] for r in results) / len(results)
    avg_spd = sum(r["parallel"]["fanout_speedup"] for r in results) / len(results)
    avg_e2e = sum(r["serial"]["wall"] / r["parallel"]["wall"] for r in results) / len(results)

    print("=" * 62)
    print("Parallel vs Serial 对比（" + str(len(results)) + " 题）")
    print("=" * 62)
    print(f"{'指标':<18}{'并行(ThreadPool)':<18}{'串行(for循环)':<18}")
    print(f"{'平均墙钟(s)':<18}{avg_p:<18.2f}{avg_s:<18.2f}")
    print(f"{'fan-out 平均加速':<18}{avg_spd:<18.2f}x{'—':<18}")
    print(f"{'端到端平均加速':<18}{avg_e2e:<18.2f}x{'—':<18}")
    print("\n结论：fan-out 段把 N 个独立子任务墙钟从 sum 压到 ≈max；"
          "端到端加速低于 fan-out 加速，因为依赖边与聚合段串行（Amdahl 定律）。")

    out = {"summary": {"avg_parallel_s": round(avg_p, 2),
                        "avg_serial_s": round(avg_s, 2),
                        "avg_fanout_speedup": round(avg_spd, 2),
                        "avg_e2e_speedup": round(avg_e2e, 2)},
           "details": results}
    out_path = Path(__file__).parent.parent / "outputs" / "eval_compare.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out_path}")


if __name__ == "__main__":
    main()
