"""Parallel vs Serial A/B 对比：客服场景

每个问题 parallel(ThreadPool) 和 serial(for 循环) 各跑一次，
输出墙钟/加速对比表 + outputs/eval_compare.json。
"""
import json, time, os, logging, argparse
from agents import run_customer_service

logging.basicConfig(level=logging.WARNING)

QUESTIONS = [
    "帮我查一下订单 A100002 的物流到哪了，给订单 A100003 申请退款原因是商品质量问题，再问下退货政策是什么",
    "查订单 A100001 物流状态，并问下保修期是多久，还有发票怎么开",
    "订单 A100004 还没发货吗？顺便查下配送范围覆盖哪些地区，A100005 为什么退款了",
    "A100003 申请退款说商品损坏，同时查下退货政策和会员等级规则",
]


def run_one(q, serial=False):
    t0 = time.time()
    r = run_customer_service(q, serial=serial)
    return {"wall": round(time.time() - t0, 2),
            "n_sub": len(r["subagents"]),
            "answer": r["final_answer"][:120],
            "parallel_stats": r["parallel_stats"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=4, help="跑前 N 题")
    args = ap.parse_args()
    qs = QUESTIONS[:args.limit]

    print(f"\n{'='*88}")
    print(f"{'问题':<50}{'并行墙钟':>10}{'串行墙钟':>10}{'子客服':>8}{'加速':>8}")
    print("-" * 88)

    records = []
    for q in qs:
        short = q[:48] + ".." if len(q) > 48 else q
        rp = run_one(q, serial=False)
        rs = run_one(q, serial=True)
        sp = (rs["wall"] / rp["wall"]) if rp["wall"] else 0
        print(f"{short:<50}{rp['wall']:>9}s{rs['wall']:>9}s{rp['n_sub']:>7}×{sp:>6.2f}×")
        records.append({"question": q, "parallel": rp, "serial": rs, "speedup": round(sp, 2)})

    avg_p = sum(r["parallel"]["wall"] for r in records) / len(records)
    avg_s = sum(r["serial"]["wall"] for r in records) / len(records)
    print("-" * 88)
    print(f"{'平均':<50}{avg_p:>9}s{avg_s:>9}s{'':>7}{(avg_s/avg_p):>7.2f}×")
    print(f"\n总墙钟并行加速: {avg_s/avg_p:.2f}×（串行 {avg_s}s → 并行 {avg_p}s）")

    os.makedirs("../outputs", exist_ok=True)
    with open("../outputs/eval_compare.json", "w", encoding="utf-8") as f:
        json.dump({"records": records,
                   "avg_parallel": avg_p, "avg_serial": avg_s,
                   "avg_speedup": round(avg_s / avg_p, 2)}, f, ensure_ascii=False, indent=2)
    print("结果已存 outputs/eval_compare.json")


if __name__ == "__main__":
    main()
