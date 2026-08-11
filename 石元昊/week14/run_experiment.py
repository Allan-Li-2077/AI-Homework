"""
自进化 Agent 作业 — 主实验脚本

实验流程：
  1. 备份初始 Skill
  2. 基线评估（优化前）
  3. 迭代优化 Skill（最多 3 轮，每轮：评估→LLM重写→再评估）
  4. 最终评估（优化后）
  5. 生成三维度对比报告（准确率 / token 消耗 / 文档长度）

运行方式：
  cd "week14 自进化agent/homework"
  export DEEPSEEK_API_KEY="sk-xxxx"
  python src/run_experiment.py

预期效果：
  - 准确率：初始冗长 Skill 下 Agent 可能遗漏关键数字，优化后结构化 Skill 提升命中率
  - Token 消耗：精简后的 Skill 文档减少 prompt_tokens（预计 30-50%）
  - 响应长度：Agent 在结构化 Skill 下回答更简洁（平均字数减少）
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from skill_manager import SkillManager
from travel_agent import TravelAgent
from evaluator import TravelEvaluator
from skill_optimizer import SkillOptimizer

SKILLS_DIR   = ROOT / "skills"
EVAL_SET     = ROOT / "data" / "eval_set.json"
KNOWLEDGE    = ROOT / "data" / "travel_knowledge.md"
OUTPUTS_DIR  = ROOT / "outputs"
REPORT_FILE  = OUTPUTS_DIR / "comparison_report.json"


def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("错误: 请先设置环境变量 DEEPSEEK_API_KEY")
        print("  export DEEPSEEK_API_KEY='sk-xxxxxx'")
        sys.exit(1)

    print("=" * 64)
    print("  自进化 Agent 作业 — 旅行规划 Skill 优化实验")
    print("=" * 64)

    # ── 初始化 ────────────────────────────────────────────────
    OUTPUTS_DIR.mkdir(exist_ok=True)
    sm = SkillManager(str(SKILLS_DIR), str(OUTPUTS_DIR))
    ev = TravelEvaluator(str(EVAL_SET))
    agent = TravelAgent(sm)
    optimizer = SkillOptimizer(sm, ev, knowledge_path=str(KNOWLEDGE))

    initial_skills = sm.load_all()
    skill_name = list(initial_skills.keys())[0]
    initial_content = initial_skills[skill_name]
    print(f"\n  目标 Skill: {skill_name}")
    print(f"  初始长度:   {len(initial_content)} 字符")
    print(f"  评估题目:   {len(ev.questions)} 题")

    # ── 备份初始版本 ──────────────────────────────────────────
    sm.save(skill_name, initial_content, reason="初始版本备份")
    sm.backup()
    print(f"  ✓ 已备份初始 Skill")

    # ── 基线评估 ──────────────────────────────────────────────
    print(f"\n{'─' * 64}")
    print("  基线评估（优化前）")
    print(f"{'─' * 64}")
    baseline = ev.run_eval(agent)
    ev.print_report(baseline, "基线评估（初始 Skill）")

    # ── 迭代优化 ──────────────────────────────────────────────
    print(f"\n{'─' * 64}")
    print("  迭代优化 Skill")
    print(f"{'─' * 64}")
    opt_rounds = optimizer.iterative_optimize(
        agent, skill_name=skill_name,
        max_rounds=3, patience=2,
    )

    # ── 最终评估 ──────────────────────────────────────────────
    print(f"\n{'─' * 64}")
    print("  最终评估（优化后）")
    print(f"{'─' * 64}")
    final = ev.run_eval(agent)
    ev.print_report(final, "最终评估（优化后 Skill）")

    # ── 对比报告 ──────────────────────────────────────────────
    final_content = sm.get(skill_name) or ""
    _print_comparison(baseline, final, initial_content, final_content, opt_rounds)

    # ── 保存报告 ──────────────────────────────────────────────
    report = _build_report(baseline, final, initial_content, final_content, opt_rounds)
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ 对比报告已保存: {REPORT_FILE}")

    # ── Skill 版本历史 ────────────────────────────────────────
    print(f"\n  Skill 版本历史:")
    for h in sm.get_history(skill_name):
        print(f"    v{h['version']} [{h['action']}] {h['time'][:19]} {h['reason'][:60]}")

    print(f"\n{'=' * 64}")
    print("  实验完成！")
    print(f"{'=' * 64}")


def _print_comparison(baseline: dict, final: dict,
                      old_skill: str, new_skill: str, opt_rounds: list):
    """打印三维度对比表"""
    bs, fs = baseline["agent_stats"], final["agent_stats"]

    acc_delta = final["pass_rate"] - baseline["pass_rate"]
    score_delta = final["avg_score"] - baseline["avg_score"]
    token_delta = fs["total_tokens"] - bs["total_tokens"]
    token_pct = (token_delta / bs["total_tokens"] * 100) if bs["total_tokens"] else 0
    prompt_delta = fs["prompt_tokens"] - bs["prompt_tokens"]
    prompt_pct = (prompt_delta / bs["prompt_tokens"] * 100) if bs["prompt_tokens"] else 0
    skill_len_delta = len(new_skill) - len(old_skill)
    skill_len_pct = (skill_len_delta / len(old_skill) * 100) if len(old_skill) else 0
    time_delta = fs["total_time"] - bs["total_time"]

    # 计算平均回答长度
    avg_ans_before = sum(d.get("answer_chars", 0) for d in baseline.get("details", [])) / max(len(baseline.get("details", [])), 1)
    avg_ans_after = sum(d.get("answer_chars", 0) for d in final.get("details", [])) / max(len(final.get("details", [])), 1)
    ans_delta = avg_ans_after - avg_ans_before

    print(f"\n{'=' * 64}")
    print("  📊 优化前后对比")
    print(f"{'=' * 64}")
    print(f"  ┌────────────────────────────────────────────────────────────┐")
    print(f"  │  指标                    │  优化前        │  优化后        │  变化    │")
    print(f"  ├────────────────────────────────────────────────────────────┤")
    print(f"  │  通过率                  │  {baseline['pass_rate']:>6.0%}       │  {final['pass_rate']:>6.0%}       │  {acc_delta:+.0%}   │")
    print(f"  │  平均分                  │  {baseline['avg_score']:>6.1f}       │  {final['avg_score']:>6.1f}       │  {score_delta:+.1f}   │")
    print(f"  │  总 Token 消耗           │  {bs['total_tokens']:>6d}       │  {fs['total_tokens']:>6d}       │  {token_pct:+.0f}%   │")
    print(f"  │  总 Prompt Token         │  {bs['prompt_tokens']:>6d}       │  {fs['prompt_tokens']:>6d}       │  {prompt_pct:+.0f}%   │")
    print(f"  │  平均 Prompt Token/次    │  {bs['avg_prompt_tokens']:>6.1f}       │  {fs['avg_prompt_tokens']:>6.1f}       │  {fs['avg_prompt_tokens']-bs['avg_prompt_tokens']:+.1f}   │")
    print(f"  │  Skill 文档长度          │  {len(old_skill):>6d} 字符  │  {len(new_skill):>6d} 字符  │  {skill_len_pct:+.0f}%   │")
    print(f"  │  平均回答字数            │  {avg_ans_before:>6.0f} 字     │  {avg_ans_after:>6.0f} 字     │  {ans_delta:+.0f}    │")
    print(f"  │  总耗时 (秒)             │  {bs['total_time']:>6.1f}       │  {fs['total_time']:>6.1f}       │  {time_delta:+.1f}   │")
    print(f"  └────────────────────────────────────────────────────────────┘")

    # 分类对比
    print(f"\n  分类通过率对比:")
    all_cats = sorted(set(list(baseline["by_category"].keys()) + list(final["by_category"].keys())))
    for cat in all_cats:
        b_cat = baseline["by_category"].get(cat, {"pass_rate": 0, "passed": 0, "total": 0, "avg_score": 0})
        f_cat = final["by_category"].get(cat, {"pass_rate": 0, "passed": 0, "total": 0, "avg_score": 0})
        d = f_cat["pass_rate"] - b_cat["pass_rate"]
        print(f"    {cat:<12}  前: {b_cat['pass_rate']:.0%} ({b_cat['passed']}/{b_cat['total']})  "
              f"后: {f_cat['pass_rate']:.0%} ({f_cat['passed']}/{f_cat['total']})  "
              f"Δ={d:+.0%}")


def _build_report(baseline, final, old_skill, new_skill, opt_rounds):
    """构建 JSON 报告"""
    bs, fs = baseline["agent_stats"], final["agent_stats"]
    return {
        "generated_at": datetime.now().isoformat(),
        "baseline": {
            "pass_rate": baseline["pass_rate"],
            "avg_score": baseline["avg_score"],
            "agent_stats": bs,
            "skill_char_count": len(old_skill),
        },
        "final": {
            "pass_rate": final["pass_rate"],
            "avg_score": final["avg_score"],
            "agent_stats": fs,
            "skill_char_count": len(new_skill),
        },
        "improvement": {
            "pass_rate_delta": round(final["pass_rate"] - baseline["pass_rate"], 3),
            "score_delta": round(final["avg_score"] - baseline["avg_score"], 1),
            "token_change_pct": round(
                (fs["total_tokens"] - bs["total_tokens"]) / max(bs["total_tokens"], 1) * 100, 1
            ),
            "prompt_token_change_pct": round(
                (fs["prompt_tokens"] - bs["prompt_tokens"]) / max(bs["prompt_tokens"], 1) * 100, 1
            ),
            "skill_length_change_pct": round(
                (len(new_skill) - len(old_skill)) / max(len(old_skill), 1) * 100, 1
            ),
        },
        "optimization_rounds": [
            {
                "round": r["round"],
                "analysis": r["optimization"].get("analysis", "")[:200],
                "changes": r["optimization"].get("changes", "")[:200],
                "failures_before": r["optimization"].get("failures_before", 0),
                "old_chars": r["optimization"].get("old_char_count", 0),
                "new_chars": r["optimization"].get("new_char_count", 0),
                "pass_rate_before": r["eval_before"]["pass_rate"],
                "pass_rate_after": r["eval_after"]["pass_rate"],
            }
            for r in opt_rounds
        ],
        "baseline_details": baseline.get("details", []),
        "final_details": final.get("details", []),
    }


if __name__ == "__main__":
    main()
