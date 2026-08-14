"""
求职公司调研 - 对比评测脚本
严格仿照 market_research_subagents eval 思路：同一题分别用 并行 / 串行 跑
融合本项目的亮点：加第 3-4 维度（图谱复用加速、纯搜索 vs 图谱一致性）
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents import ResearchAgents
from src.build_graph import get_driver as neo4j_get_driver

# 严格仿照 market_research_subagents：评测结果输出到 outputs/eval_compare.json
OUTPUT_DIR = Path(__file__).parent.parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)
RESULT_JSON = OUTPUT_DIR / "eval_compare.json"

# ============================================================
# 4 道评测题：2 道深度调研 + 1 道对比 + 1 道多公司交叉
# ============================================================
EVAL_CASES = [
    # (展示名, company, question)
    ("字节跳动_全维度",
     "字节跳动",
     "业务板块、薪资待遇（校招算法/后端）、技术栈、面试流程、行业前景"),

    ("商汤科技_全维度",
     "商汤科技",
     "主营业务、薪资待遇、技术栈与工程文化、面试流程、员工口碑与前景"),

    ("科大讯飞_全维度",
     "科大讯飞",
     "主营业务构成、研发投入、薪资、面试、AI技术栈与未来前景"),

    ("百度_全维度",
     "百度",
     "搜索引擎/AI大模型/自动驾驶三大板块、薪资水平、技术栈、面试经验"),
]


@dataclass
class CaseResult:
    case_name: str
    company: str
    question: str
    # 并行版
    parallel_total_ms: int = 0
    parallel_dispatch_wall_ms: int = 0
    parallel_dispatch_serial_sum_ms: int = 0
    parallel_answer: str = ""
    # 串行版（dispatch 退化成 for 循环）
    serial_total_ms: int = 0
    serial_dispatch_sum_ms: int = 0
    serial_answer: str = ""
    # 图谱命中（第二次同一公司）
    graph_hit_ms: int = 0
    graph_subgraph_triples: int = 0
    graph_answer: str = ""
    # 加速比
    dispatch_speedup_x: float = 0  # 只看 dispatch 段
    end_to_end_speedup_x: float = 0  # 总墙钟
    graph_reuse_speedup_x: float = 0  # 第二次查图 vs 第一次调研（并行版）

    def to_dict(self):
        return self.__dict__


def run_case(case_name: str, company: str, question: str) -> CaseResult:
    cr = CaseResult(case_name=case_name, company=company, question=question)

    # ---------- 第 1 组：并行模式（serial=False）----------
    print(f"\n===== [{case_name}] 并行模式 =====")
    a_p = ResearchAgents(serial=False)
    t0 = time.perf_counter()
    tr_p = a_p.research(f"{company} 求职调研：{question}")
    cr.parallel_total_ms = int((time.perf_counter() - t0) * 1000)
    cr.parallel_answer = tr_p.final_answer
    cr.parallel_dispatch_wall_ms = tr_p.parallel.get("wall_ms", 0)
    cr.parallel_dispatch_serial_sum_ms = tr_p.parallel.get("serial_sum_ms", 0)
    if cr.parallel_dispatch_wall_ms > 0:
        cr.dispatch_speedup_x = round(cr.parallel_dispatch_serial_sum_ms / cr.parallel_dispatch_wall_ms, 2)

    # ---------- 第 2 组：串行模式（serial=True）dispatch 退化成 for ----------
    print(f"===== [{case_name}] 串行模式（A/B 基线）=====")
    a_s = ResearchAgents(serial=True)
    t0 = time.perf_counter()
    tr_s = a_s.research(f"{company} 求职调研：{question}")
    cr.serial_total_ms = int((time.perf_counter() - t0) * 1000)
    cr.serial_answer = tr_s.final_answer
    # 串行模式下 dispatch 没有"加速"，直接拿并行的 sum 跟串行总 dispatch 段比更准
    cr.serial_dispatch_sum_ms = tr_s.parallel.get("serial_sum_ms", 0) or cr.parallel_dispatch_serial_sum_ms
    if cr.parallel_total_ms > 0:
        cr.end_to_end_speedup_x = round(cr.serial_total_ms / cr.parallel_total_ms, 2)

    # ---------- 第 3 组：图谱命中版（同一公司 research_or_query → 应该走图）----------
    print(f"===== [{case_name}] 图谱复用（第二次查，应该直接走 Neo4j）=====")
    t0 = time.perf_counter()
    a_g = ResearchAgents(serial=False)
    tr_g = a_g.research_or_query(company, question)
    cr.graph_hit_ms = int((time.perf_counter() - t0) * 1000)
    cr.graph_subgraph_triples = tr_g.graph_info.get("subgraph_triples", 0)
    cr.graph_answer = tr_g.graph_info.get("answer", "") or tr_g.final_answer
    if cr.graph_hit_ms > 0:
        cr.graph_reuse_speedup_x = round(cr.parallel_total_ms / cr.graph_hit_ms, 2)

    print(f"  并行总墙钟: {cr.parallel_total_ms} ms  | 串行总墙钟: {cr.serial_total_ms} ms  | 端到端加速: {cr.end_to_end_speedup_x}x")
    print(f"  dispatch段并行: {cr.parallel_dispatch_wall_ms} ms  | dispatch串行总和: {cr.parallel_dispatch_serial_sum_ms} ms  | dispatch加速: {cr.dispatch_speedup_x}x")
    print(f"  图谱复用: {cr.graph_hit_ms} ms  | 子图三元组: {cr.graph_subgraph_triples}  | 复用加速: {cr.graph_reuse_speedup_x}x")
    return cr


def summarize(results: list[CaseResult]) -> dict:
    return {
        "cases": len(results),
        "dispatch_speedup_x_avg": round(statistics.mean([r.dispatch_speedup_x for r in results if r.dispatch_speedup_x]), 2),
        "e2e_speedup_x_avg": round(statistics.mean([r.end_to_end_speedup_x for r in results if r.end_to_end_speedup_x]), 2),
        "graph_reuse_speedup_x_avg": round(statistics.mean([r.graph_reuse_speedup_x for r in results if r.graph_reuse_speedup_x]), 2),
        "parallel_total_ms_avg": int(statistics.mean([r.parallel_total_ms for r in results])),
        "serial_total_ms_avg": int(statistics.mean([r.serial_total_ms for r in results])),
        "graph_hit_ms_avg": int(statistics.mean([r.graph_hit_ms for r in results])),
    }


def main():
    try:
        # 测试 Neo4j 通不通
        d = neo4j_get_driver()
        d.close()
        print("[eval] Neo4j 连接 OK")
    except Exception as e:
        print(f"[eval] 警告：Neo4j 连不上：{e}（图谱复用维度会失效，但并行/串行对比仍可进行）")

    results: list[CaseResult] = []
    for name, comp, q in EVAL_CASES:
        results.append(run_case(name, comp, q))

    summary = summarize(results)
    out = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "cases": [r.to_dict() for r in results],
    }
    # 严格仿照 market_research_subagents：用 Path.write_text 输出
    RESULT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"【EVAL 汇总】—— {RESULT_JSON}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("=" * 70)
    print("每个 case 的详细数据（含答案全文）已写入 outputs/eval_compare.json")


if __name__ == "__main__":
    main()
