# -*- coding: utf-8 -*-
"""
CLI 主入口：运行 Skill 自进化实验，纯命令行。

子命令：
  python src/runner.py reset   还原 skills/ 初始状态，清空 outputs/
  python src/runner.py run     跑一次完整实验（基线 -> 演示脚本自进化 -> 最终评估 -> naive基线对比）
  python src/runner.py report  读取已有 evolution_log.json 打印摘要（不跑LLM）

产出：
  outputs/skills_original/       初始Skill备份（reset从这里还原，永不覆盖）
  outputs/skill_versions/        {name}_history.json 全量版本历史
  outputs/skill_snapshots/       {name}_v{N}.md 每版独立快照
  outputs/eval_runs/             每次评估详细数据
  outputs/evolution_log.json     总日志
  outputs/final_report.md        准确率提升 + token节省量 最终报告
"""

import os
import sys
import json
import shutil
import argparse
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from skill_manager import SkillManager
from evaluator import Evaluator
from agent import OncallAssistantAgent
from naive_baseline import NaiveBaselineAgent
from background_reviewer import BackgroundReviewer

SKILLS_DIR = ROOT / "skills"
SKILLS_ORIG = ROOT / "outputs" / "skills_original"
EVAL_SET = ROOT / "data" / "eval_set.json"
DEMO_SCRIPT = ROOT / "data" / "demo_script.json"
POLICIES = ROOT / "data" / "policies.md"
VERSIONS_DIR = ROOT / "outputs" / "skill_versions"
EVAL_RUNS_DIR = ROOT / "outputs" / "eval_runs"
EVOL_LOG = ROOT / "outputs" / "evolution_log.json"
FINAL_REPORT = ROOT / "outputs" / "final_report.md"


# ── 备份 / 还原 ──────────────────────────────────────────────────────────────

def ensure_original(sm: SkillManager):
    if not SKILLS_ORIG.exists():
        shutil.copytree(SKILLS_DIR, SKILLS_ORIG)
        print(f"+ 首次运行：原始 Skills 备份至 {SKILLS_ORIG.name}/")
        for skill_name in sm.load_all():
            sm._save_version(skill_name, action="initial", reason="初始版本")
    else:
        print("+ 检测到原始备份，已跳过覆盖")


def restore_from_original():
    if not SKILLS_ORIG.exists():
        raise RuntimeError("原始备份不存在，请先运行 'python src/runner.py run' 一次以建立备份")
    if SKILLS_DIR.exists():
        shutil.rmtree(SKILLS_DIR)
    shutil.copytree(SKILLS_ORIG, SKILLS_DIR)
    if VERSIONS_DIR.exists():
        shutil.rmtree(VERSIONS_DIR)
    snapshots = ROOT / "outputs" / "skill_snapshots"
    if snapshots.exists():
        shutil.rmtree(snapshots)
    if EVAL_RUNS_DIR.exists():
        shutil.rmtree(EVAL_RUNS_DIR)
    print("+ 已还原初始 Skills，清空上次版本历史")


def cmd_reset(_args):
    """还原 skills/ 到初始状态，清空 outputs/ 中的运行产物（保留 skills_original 备份本身）。"""
    if not SKILLS_ORIG.exists():
        print("尚无原始备份，无需还原。首次 'run' 时会自动创建备份。")
        return
    restore_from_original()
    if EVOL_LOG.exists():
        EVOL_LOG.unlink()
    if FINAL_REPORT.exists():
        FINAL_REPORT.unlink()
    print("+ reset 完成")


# ── Probe / Full Eval ─────────────────────────────────────────────────────────

def run_probe_eval(agent: OncallAssistantAgent, evaluator: Evaluator,
                    probe_ids: list[int], run_id: str, label: str,
                    sm: SkillManager) -> dict:
    EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    total, correct = 0, 0
    by_category: dict = {}
    answers: dict = {}
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for qid in probe_ids:
        q = evaluator.questions[qid]
        answer = agent.answer(q["question"])
        ok, reason = evaluator.evaluate_answer(answer, qid)
        total += 1
        cat = q["category"]
        by_category.setdefault(cat, {"total": 0, "correct": 0})
        by_category[cat]["total"] += 1
        if ok:
            correct += 1
            by_category[cat]["correct"] += 1
        answers[str(qid)] = {"answer": answer, "correct": ok, "fail_reason": reason if not ok else ""}
        if agent.last_usage:
            for k in usage_total:
                usage_total[k] += agent.last_usage.get(k, 0)

    for cat in by_category.values():
        cat["accuracy"] = round(cat["correct"] / cat["total"], 3)

    result = {
        "run_id": run_id,
        "label": label,
        "timestamp": datetime.now().isoformat(),
        "skill_versions_active": sm.get_active_versions(),
        "summary": {"total": total, "correct": correct, "accuracy": round(correct / total, 3)},
        "token_usage": usage_total,
        "avg_prompt_tokens": round(usage_total["prompt_tokens"] / total, 1) if total else 0,
        "by_category": by_category,
        "answers": answers,
    }
    (EVAL_RUNS_DIR / f"{run_id}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def run_full_eval(agent: OncallAssistantAgent, evaluator: Evaluator,
                   run_id: str, label: str, sm: SkillManager) -> dict:
    all_ids = list(evaluator.questions.keys())
    return run_probe_eval(agent, evaluator, all_ids, run_id, label, sm)


def run_naive_baseline_eval(naive_agent: NaiveBaselineAgent, evaluator: Evaluator) -> dict:
    """用完整 policies.md 塞进 prompt 的对照组，跑一遍全量 60 题，记录准确率和 token 用量。"""
    total, correct = 0, 0
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    by_category: dict = {}

    for qid, q in sorted(evaluator.questions.items()):
        answer = naive_agent.answer(q["question"])
        ok, _ = evaluator.evaluate_answer(answer, qid)
        total += 1
        cat = q["category"]
        by_category.setdefault(cat, {"total": 0, "correct": 0})
        by_category[cat]["total"] += 1
        if ok:
            correct += 1
            by_category[cat]["correct"] += 1
        if naive_agent.last_usage:
            for k in usage_total:
                usage_total[k] += naive_agent.last_usage.get(k, 0)

    for cat in by_category.values():
        cat["accuracy"] = round(cat["correct"] / cat["total"], 3)

    return {
        "label": "naive_baseline（完整政策文档塞入prompt，无Skill机制）",
        "summary": {"total": total, "correct": correct, "accuracy": round(correct / total, 3) if total else 0},
        "token_usage": usage_total,
        "avg_prompt_tokens": round(usage_total["prompt_tokens"] / total, 1) if total else 0,
        "by_category": by_category,
    }


# ── Evolution Log ─────────────────────────────────────────────────────────────

class EvolutionLog:
    def __init__(self):
        self.eval_runs: list[dict] = []
        self.nudge_events: list[dict] = []
        self.question_history: dict[str, list] = {}
        self.naive_baseline_result: dict = {}

    def add_eval_run(self, result: dict):
        self.eval_runs.append({
            "run_id": result["run_id"],
            "label": result["label"],
            "timestamp": result["timestamp"],
            "skill_versions_active": result["skill_versions_active"],
            "accuracy": result["summary"]["accuracy"],
            "correct": result["summary"]["correct"],
            "total": result["summary"]["total"],
            "avg_prompt_tokens": result.get("avg_prompt_tokens", 0),
            "by_category": {k: v["accuracy"] for k, v in result["by_category"].items()},
        })
        for qid_str, ans_data in result["answers"].items():
            self.question_history.setdefault(qid_str, []).append({
                "run_id": result["run_id"],
                "label": result["label"],
                "skill_versions": result["skill_versions_active"],
                "answer": ans_data["answer"],
                "correct": ans_data["correct"],
                "fail_reason": ans_data.get("fail_reason", ""),
            })

    def add_nudge_event(self, seq: int, block: str, actions_taken: list[dict],
                         accuracy_before: float, skill_versions_after: dict):
        self.nudge_events.append({
            "after_seq": seq,
            "block": block,
            "timestamp": datetime.now().isoformat(),
            "accuracy_before_this_block": round(accuracy_before, 3),
            "actions_taken": actions_taken,
            "skill_versions_after": skill_versions_after,
        })

    def set_naive_baseline(self, result: dict):
        self.naive_baseline_result = result

    def save(self, sm: SkillManager, evaluator: Evaluator):
        skill_snapshots = {}
        for skill_dir in SKILLS_DIR.iterdir():
            if skill_dir.is_dir():
                name = skill_dir.name
                history = sm.get_version_history(name)
                skill_snapshots[name] = [
                    {
                        "version": h["version"],
                        "time": h["time"],
                        "action": h["action"],
                        "reason": h["reason"][:120],
                        "snapshot_file": h.get("snapshot_file", ""),
                    }
                    for h in history
                ]

        question_comparison = {}
        for qid_str, history in self.question_history.items():
            qid = int(qid_str)
            q = evaluator.questions.get(qid)
            if q:
                question_comparison[qid_str] = {
                    "question": q["question"],
                    "category": q["category"],
                    "difficulty": q["difficulty"],
                    "ground_truth": q["ground_truth"],
                    "history": history,
                }

        log = {
            "generated_at": datetime.now().isoformat(),
            "skill_snapshots": skill_snapshots,
            "eval_runs": self.eval_runs,
            "nudge_events": self.nudge_events,
            "naive_baseline": self.naive_baseline_result,
            "question_comparison": question_comparison,
        }
        EVOL_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"+ evolution_log.json 已保存 ({EVOL_LOG})")


# ── 主实验流程 ────────────────────────────────────────────────────────────────

def cmd_run(_args):
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("错误: 请先设置 DEEPSEEK_API_KEY 环境变量")
        sys.exit(1)

    print("=" * 60)
    print("  谛听监控平台 一线值班助手 Agent 自进化实验")
    print("=" * 60)

    (ROOT / "outputs").mkdir(exist_ok=True)
    sm = SkillManager(str(SKILLS_DIR), str(VERSIONS_DIR))

    ensure_original(sm)
    restore_from_original()

    sm = SkillManager(str(SKILLS_DIR), str(VERSIONS_DIR))
    agent = OncallAssistantAgent(sm)
    reviewer = BackgroundReviewer(str(POLICIES), sm)
    evaluator = Evaluator(str(EVAL_SET))
    elog = EvolutionLog()

    for skill_name in sm.load_all():
        sm._save_version(skill_name, action="initial", reason="初始版本")

    script_data = json.loads(DEMO_SCRIPT.read_text(encoding="utf-8"))
    demo_questions = script_data["questions"]
    nudge_interval = script_data["nudge_interval"]
    probe_ids = script_data.get("probe_question_ids", list(range(1, 31)))

    # ── 基线评估 ─────────────────────────────────────────────────────────────
    print(f"\n{'-'*60}")
    print("基线评估（初始 Skills，无进化）")
    print("-" * 60)
    baseline = run_full_eval(agent, evaluator, "baseline", "基线（初始Skills）", sm)
    elog.add_eval_run(baseline)
    _print_summary(baseline)
    agent.conversation_history.clear()

    # ── 演示脚本 ─────────────────────────────────────────────────────────────
    print(f"\n{'-'*60}")
    print(f"演示脚本运行（{len(demo_questions)} 题，Nudge 间隔={nudge_interval}）")
    print("-" * 60)

    iters = 0
    block_correct = 0
    block_total = 0
    block_failed_turns: list[dict] = []

    for item in demo_questions:
        seq = item["seq"]
        eval_id = item["eval_id"]
        question = item["question"]
        block = item.get("block", "")

        answer = agent.answer(question)
        ok, reason = evaluator.evaluate_answer(answer, eval_id)
        block_correct += int(ok)
        block_total += 1
        iters += 1
        if not ok:
            block_failed_turns.append({"question": question, "answer": answer, "fail_reason": reason})

        status = "OK" if ok else "X "
        note = f"  [{item['note']}]" if item.get("note") else ""
        print(f"  Q{seq:02d} {status}  {question[:50]:<50}{note}")

        if iters >= nudge_interval:
            block_acc = block_correct / block_total if block_total else 0
            print(f"\n{'='*60}")
            print(f"  本块 [{block}] 完成: {block_correct}/{block_total} = {block_acc:.1%}")

            if not block_failed_turns:
                print(f"  + 本块全对，跳过 Nudge 和 Probe eval")
                elog.add_nudge_event(seq, block, [], block_acc, sm.get_active_versions())
            else:
                print(f"  * Nudge 触发（{len(block_failed_turns)} 条失败样本注入 Reviewer）")
                actions = reviewer.review(block_failed_turns)
                executed_actions = []
                for act in (actions or []):
                    try:
                        file_ = act.get("file", "SKILL.md")
                        if act["action"] == "create":
                            ok_act = sm.create(act["skill_name"], act["content"], reason=act.get("reason", ""), file=file_)
                        elif act["action"] == "patch":
                            ok_act = sm.patch(act["skill_name"], act["old_text"], act["new_text"],
                                               reason=act.get("reason", ""), file=file_)
                        else:
                            ok_act = False
                        if ok_act:
                            executed_actions.append(
                                {"action": act["action"], "skill": act["skill_name"], "file": file_,
                                 "reason": act.get("reason", "")[:80]})
                    except Exception as e:
                        print(f"  [Reviewer] 执行失败: {e}")
                print(f"  + 执行了 {len(executed_actions)} 个 Skill 操作")

                probe_run_id = f"after_nudge_seq{seq}"
                probe_label = f"Nudge后（seq={seq}, block={block}）"
                probe_result = run_probe_eval(agent, evaluator, probe_ids, probe_run_id, probe_label, sm)
                elog.add_eval_run(probe_result)
                print(f"  Probe eval: {probe_result['summary']['correct']}/{probe_result['summary']['total']} = "
                      f"{probe_result['summary']['accuracy']:.1%}")
                elog.add_nudge_event(seq, block, executed_actions, block_acc, sm.get_active_versions())

            iters = 0
            block_correct = 0
            block_total = 0
            block_failed_turns = []
            agent.conversation_history = agent.conversation_history[-5:]
            print(f"{'='*60}\n")

    # ── 最终评估 ─────────────────────────────────────────────────────────────
    print(f"\n{'-'*60}")
    print("最终评估（进化后 Skills）")
    print("-" * 60)
    final = run_full_eval(agent, evaluator, "final", "最终（进化后）", sm)
    elog.add_eval_run(final)
    _print_summary(final)

    # ── naive baseline 对照组 ───────────────────────────────────────────────
    print(f"\n{'-'*60}")
    print("对照组：完整政策文档塞入prompt（无Skill机制），跑60题算token对比")
    print("-" * 60)
    naive_agent = NaiveBaselineAgent(str(POLICIES))
    naive_result = run_naive_baseline_eval(naive_agent, evaluator)
    elog.set_naive_baseline(naive_result)
    print(f"  naive baseline 准确率: {naive_result['summary']['correct']}/{naive_result['summary']['total']} "
          f"= {naive_result['summary']['accuracy']:.1%}")
    print(f"  naive baseline 平均 prompt tokens/题: {naive_result['avg_prompt_tokens']}")
    print(f"  Skill进化后 平均 prompt tokens/题: {final['avg_prompt_tokens']}")

    # ── 汇总 + 报告 ─────────────────────────────────────────────────────────
    elog.save(sm, evaluator)
    _write_final_report(elog, baseline, final, naive_result, sm)
    print(f"\n+ 最终报告见 outputs/final_report.md")
    print(f"+ 评估详情见 outputs/eval_runs/")
    print(f"+ 各版本 Skill 见 outputs/skill_snapshots/")


def _print_summary(result: dict):
    r = result["summary"]
    print(f"总体准确率: {r['correct']}/{r['total']} = {r['accuracy']:.1%}")
    print("分类准确率:")
    for cat, stats in sorted(result["by_category"].items()):
        bar = "#" * int(stats["accuracy"] * 20)
        print(f"  {cat:<24} {stats['correct']:>2}/{stats['total']:>2}  {bar} {stats['accuracy']:.0%}")


def _write_final_report(elog: EvolutionLog, baseline: dict, final: dict, naive: dict, sm: SkillManager):
    base_acc = baseline["summary"]["accuracy"]
    final_acc = final["summary"]["accuracy"]
    naive_acc = naive["summary"]["accuracy"]
    skill_tokens = final["avg_prompt_tokens"]
    naive_tokens = naive["avg_prompt_tokens"]
    token_saving_pct = round((1 - skill_tokens / naive_tokens) * 100, 1) if naive_tokens else 0

    lines = []
    lines.append("# 自进化 Skill 实验最终报告\n")
    lines.append(f"生成时间：{datetime.now().isoformat()}\n")
    lines.append("## 一、准确率对比\n")
    lines.append("| 阶段 | 准确率 | 正确/总数 |")
    lines.append("|------|--------|-----------|")
    lines.append(f"| 基线（初始Skills，无进化） | {base_acc:.1%} | {baseline['summary']['correct']}/{baseline['summary']['total']} |")
    lines.append(f"| 进化后（自进化Skills） | {final_acc:.1%} | {final['summary']['correct']}/{final['summary']['total']} |")
    lines.append(f"| naive基线（完整政策文档塞prompt，无Skill机制） | {naive_acc:.1%} | {naive['summary']['correct']}/{naive['summary']['total']} |")
    lines.append(f"\n**准确率提升（进化后 vs 基线）：+{(final_acc - base_acc):.1%}**\n")

    lines.append("## 二、Token 消耗对比\n")
    lines.append("| 方案 | 平均 prompt tokens/题 |")
    lines.append("|------|----------------------|")
    lines.append(f"| naive基线（完整政策文档塞prompt） | {naive_tokens} |")
    lines.append(f"| 自进化Skill（最终版本） | {skill_tokens} |")
    lines.append(f"\n**Token 节省量：{token_saving_pct}%**"
                 f"（自进化Skill仅保留了失败驱动新增的必要规则，而非整份原始政策文档）\n")

    lines.append("## 三、进化轨迹（Probe eval 准确率）\n")
    lines.append("| Nudge 阶段 | 正确/总数 | 准确率 |")
    lines.append("|-----------|-----------|--------|")
    for run in elog.eval_runs:
        if run["run_id"].startswith("after_nudge"):
            lines.append(f"| {run['label']} | {run['correct']}/{run['total']} | {run['accuracy']:.1%} |")

    lines.append("\n## 四、Skill 版本历史\n")
    for name, versions in sorted(sm.get_all_version_summaries().items()):
        lines.append(f"### {name}（{len(versions)} 个版本）\n")
        for v in versions:
            lines.append(f"- v{v.get('time', '')[:19]} [{v['action']}] {v['reason'][:80]}")
        lines.append("")

    lines.append("## 五、Nudge 事件详情\n")
    for ev in elog.nudge_events:
        lines.append(f"### seq={ev['after_seq']} block={ev['block']}\n")
        lines.append(f"- 本块触发前准确率：{ev['accuracy_before_this_block']:.1%}")
        if ev["actions_taken"]:
            for act in ev["actions_taken"]:
                lines.append(f"- [{act['action']}] {act['skill']}：{act['reason']}")
        else:
            lines.append("- 本块全对，跳过 Nudge")
        lines.append("")

    FINAL_REPORT.write_text("\n".join(lines), encoding="utf-8")


# ── report 子命令（不跑LLM，只读已有日志） ─────────────────────────────────

def cmd_report(_args):
    if not EVOL_LOG.exists():
        print("尚无 evolution_log.json，请先运行 'python src/runner.py run'")
        return
    log = json.loads(EVOL_LOG.read_text(encoding="utf-8"))
    print("=" * 60)
    print("  自进化实验摘要（来自已有 evolution_log.json）")
    print("=" * 60)
    for run in log["eval_runs"]:
        print(f"  {run['label']:<40} {run['correct']:>2}/{run['total']:>2} = {run['accuracy']:.1%}"
              f"  (avg_tokens={run.get('avg_prompt_tokens', '-')})")
    naive = log.get("naive_baseline", {})
    if naive:
        print(f"\n  naive基线: {naive['summary']['correct']}/{naive['summary']['total']} = "
              f"{naive['summary']['accuracy']:.1%}  (avg_tokens={naive.get('avg_prompt_tokens', '-')})")
    print(f"\n  Skill 版本数：")
    for name, versions in log["skill_snapshots"].items():
        print(f"    {name}: {len(versions)} 个版本")
    if FINAL_REPORT.exists():
        print(f"\n  完整报告见: {FINAL_REPORT}")


def main():
    parser = argparse.ArgumentParser(description="Skill 自进化实验 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("reset", help="还原 skills/ 初始状态，清空 outputs/ 运行产物").set_defaults(func=cmd_reset)
    sub.add_parser("run", help="跑一次完整实验").set_defaults(func=cmd_run)
    sub.add_parser("report", help="打印已有 evolution_log.json 摘要").set_defaults(func=cmd_report)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
