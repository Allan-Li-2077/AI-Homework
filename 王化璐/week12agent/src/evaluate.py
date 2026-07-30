"""
对比评估：手写 Prompt 解析版 vs Function Calling 版

评估维度：
  1. 格式稳定性（手写版专属：成功解析率）
  2. 步骤数（完成同一问题用了几步）
  3. 耗时（秒）
  4. 是否给出 Final Answer（成功率）

使用方式：
  python evaluate.py
  python evaluate.py --output ../evaluation/compare_result.json
"""

import os
import sys
import json
import time
import argparse
import logging

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.WARNING)

EVAL_QUESTIONS = [
    {
        "id": "Q1",
        "question": "Transformer和RNN的主要区别是什么？",
        "expected_tools": ["concept_compare"],
        "note": "概念对比",
    },
    {
        "id": "Q2",
        "question": "Attention Is All You Need这篇论文的核心贡献是什么？",
        "expected_tools": ["paper_summary"],
        "note": "论文摘要检索",
    },
    {
        "id": "Q3",
        "question": "BERT模型的关键技术点有哪些？",
        "expected_tools": ["ai_concept_lookup"],
        "note": "概念查询",
    },
    {
        "id": "Q4",
        "question": "Transformer中的多头注意力机制是如何工作的？",
        "expected_tools": ["rag_search"],
        "note": "论文细节检索",
    },
    {
        "id": "Q5",
        "question": "请预测未来十年AI的发展方向",
        "expected_tools": [],
        "note": "超出能力边界，应拒绝作答",
    },
]


def _run_single(mode: str, question: str, max_steps: int = 10) -> dict:
    """运行单个问题，收集评估指标"""
    if mode == "manual":
        from react_manual import run as react_run
    else:
        from react_function_calling import run as react_run

    steps        = []
    parse_errors = 0
    start        = time.time()
    final_answer = None
    success      = False

    for step_data in react_run(question, max_steps=max_steps):
        steps.append(step_data)
        if step_data["type"] == "unparseable":
            parse_errors += 1
        if step_data["type"] == "final":
            final_answer = step_data["answer"]
            success = True

    elapsed = time.time() - start
    action_steps = [s for s in steps if s["type"] == "action"]
    tools_used   = [s["action"] for s in action_steps]

    return {
        "mode":         mode,
        "total_steps":  len(action_steps),
        "elapsed_s":    round(elapsed, 1),
        "success":      success,
        "parse_errors": parse_errors,
        "tools_used":   tools_used,
        "final_answer": (final_answer or "")[:200],
    }


def evaluate(output_path: str | None = None, max_steps: int = 10):
    results = []

    for q in EVAL_QUESTIONS:
        print(f"\n{'─'*60}")
        print(f"[{q['id']}] {q['question']}")
        print(f"  预期工具: {q['expected_tools']}  ({q['note']})")

        for mode in ["manual", "fc"]:
            print(f"  运行 [{mode}]...", end=" ", flush=True)
            r = _run_single(mode, q["question"], max_steps)
            print(f"步骤:{r['total_steps']}  耗时:{r['elapsed_s']}s  成功:{r['success']}")
            results.append({**q, **r})

    print(f"\n{'='*60}")
    print(f"{'ID':<4} {'Mode':<8} {'Steps':<7} {'Time(s)':<9} {'Success':<8} {'ParseErr'}")
    print(f"{'─'*60}")
    for r in results:
        print(
            f"{r['id']:<4} {r['mode']:<8} {r['total_steps']:<7} "
            f"{r['elapsed_s']:<9} {str(r['success']):<8} {r['parse_errors']}"
        )

    for mode in ["manual", "fc"]:
        mode_results = [r for r in results if r["mode"] == mode]
        avg_steps   = sum(r["total_steps"] for r in mode_results) / len(mode_results)
        avg_time    = sum(r["elapsed_s"]    for r in mode_results) / len(mode_results)
        success_rate = sum(r["success"] for r in mode_results) / len(mode_results)
        total_errors = sum(r["parse_errors"] for r in mode_results)
        print(f"\n[{mode}] 平均步数:{avg_steps:.1f}  平均耗时:{avg_time:.1f}s  "
              f"成功率:{success_rate:.0%}  解析错误总数:{total_errors}")

    if output_path:
        def _safe(v):
            return v.item() if hasattr(v, "item") else v

        safe_results = [{k: _safe(v) for k, v in r.items()} for r in results]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(safe_results, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存至 {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",    default=None, help="保存 JSON 结果的路径")
    parser.add_argument("--max_steps", type=int, default=10)
    args = parser.parse_args()
    evaluate(args.output, args.max_steps)