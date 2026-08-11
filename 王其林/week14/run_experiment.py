"""
主程序：Skill 自进化实验（4 轮 × 20 题，混合主题，ReAct Agent + 自动迭代）。

流程（参考 self_evolving_agent 的 demo_script 设计）：
  1. 备份初始 Skill（outputs/skills_original，只建一次）并还原，保证可重复运行
  2. 从 data/demo_script.json 加载题目顺序与 nudge_interval（混合4个主题域）
  3. 4 轮进化（每轮 20 题，每轮混合 唐诗5+宋词5+诗派典故5+格律理论5）：
       轮1：用 v1 回答 seq 1-20 → 评估 → 进化 → v2
       轮2：用 v2 回答 seq 21-40 → 评估 → 进化 → v3
       轮3：用 v3 回答 seq 41-60 → 评估 → 进化 → v4
       轮4：用 v4 回答 seq 61-80 → 评估 → 进化 → v5
     每轮混合多主题，确保与 Skill 已有知识有部分重叠，准确率呈上升趋势
  4. 对比 4 轮指标趋势（准确率 / token / ReAct 轮数 / 耗时 / 成本）+ Skill 版本链

运行方式：
  export DEEPSEEK_API_KEY="sk-xxxx"
  python3.13 src/run_experiment.py                    # 默认 ReAct 2 轮
  python3.13 src/run_experiment.py --react-rounds 2
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
from agent import ReActCodingAgent, _tokenize
from optimizer import SkillOptimizer

SKILLS_DIR = ROOT / "skills"
SKILLS_ORIG = ROOT / "outputs" / "skills_original"
TASKS = ROOT / "data" / "tasks.json"
DEMO_SCRIPT = ROOT / "data" / "demo_script.json"
OUTPUTS = ROOT / "outputs"
VERSIONS_DIR = OUTPUTS / "skill_versions"
EVAL_RUNS = OUTPUTS / "eval_runs"
EVOL_LOG = OUTPUTS / "evolution_log.json"

# 成本估算单价（DeepSeek deepseek-chat 约 ¥1/M input + ¥2/M output）
PRICE_IN = 1e-6
PRICE_OUT = 2e-6


# ── 备份 / 还原（保证实验可重复） ─────────────────────────────────────────────

def ensure_original(sm: SkillManager):
    if not SKILLS_ORIG.exists():
        shutil.copytree(SKILLS_DIR, SKILLS_ORIG)
        print(f"✓ 首次运行：原始 Skill 备份至 outputs/skills_original/")


def restore_from_original():
    if not SKILLS_ORIG.exists():
        raise RuntimeError("原始备份不存在，请删除 outputs/ 后重新运行")
    if SKILLS_DIR.exists():
        shutil.rmtree(SKILLS_DIR)
    shutil.copytree(SKILLS_ORIG, SKILLS_DIR)
    for d in (VERSIONS_DIR, OUTPUTS / "skill_snapshots", EVAL_RUNS):
        if d.exists():
            shutil.rmtree(d)
    print("✓ 已还原初始 Skill，清空版本历史/快照/评估记录")


# ── 单轮评估 ──────────────────────────────────────────────────────────────────

def run_round(agent: ReActCodingAgent, group: list[dict], round_idx: int,
              sm: SkillManager) -> dict:
    """用当前最新 Skill 回答一组题，返回指标 + 失败样本 + 进化事件。
    agent 的 nudge_interval 由调用方设置，第 nudge_interval 题后自动触发一次进化。"""
    EVAL_RUNS.mkdir(parents=True, exist_ok=True)
    pt = ct = tt = rrs_sum = 0
    elapsed_sum = 0.0
    per_task = []

    for t in group:
        versions_active = dict(sm.get_active_versions())
        r = agent.answer(t["task"], t)
        ok, reason = agent.evaluator.evaluate_answer(r["answer"], t)
        per_task.append({
            "id": t["id"], "title": t["title"], "task": t["task"],
            "skill_version": versions_active.get("poetry_skill", 0),
            "answer": r["answer"], "correct": ok,
            "fail_reason": reason if not ok else "",
            "prompt_tokens": r["prompt_tokens"],
            "completion_tokens": r["completion_tokens"],
            "total_tokens": r["prompt_tokens"] + r["completion_tokens"],
            "react_rounds": r["react_rounds"], "elapsed": r["elapsed"],
        })
        pt += r["prompt_tokens"]
        ct += r["completion_tokens"]
        tt += r["prompt_tokens"] + r["completion_tokens"]
        rrs_sum += r["react_rounds"]
        elapsed_sum += r["elapsed"]
        mark = "✓" if ok else "✗"
        print(f"  T{t['id']:02d} {mark}  v{versions_active.get('poetry_skill', 0)}  "
              f"{t['title']:<22} {r['react_rounds']}轮 {r['prompt_tokens'] + r['completion_tokens']}tok"
              + (f"  ✗{reason[:30]}" if not ok else ""))

    n = len(group)
    correct = sum(1 for p in per_task if p["correct"])
    failed_turns = [
        {"question": p["task"], "title": p["title"],
         "answer": p["answer"], "fail_reason": p["fail_reason"]}
        for p in per_task if not p["correct"]
    ]
    summary = {
        "round": round_idx,
        "skill_version": versions_active.get("poetry_skill", 0),
        "total": n, "correct": correct,
        "accuracy": round(correct / n, 4),
        "prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt,
        "avg_tokens_per_question": round(tt / n, 1),
        "avg_react_rounds": round(rrs_sum / n, 2),
        "elapsed_total": round(elapsed_sum, 3),
        "avg_elapsed_per_question": round(elapsed_sum / n, 3),
        "cost_estimate_yuan": round(pt * PRICE_IN + ct * PRICE_OUT, 6),
    }
    result = {"summary": summary, "per_task": per_task, "failed_turns": failed_turns}
    # 进化事件（第 20 题后 agent.answer 内部已触发 evolve）
    if agent.evolution_events:
        ev = agent.evolution_events[-1]
        result["evolution"] = {
            "mode": ev.get("mode", ""),
            "skipped": bool(ev.get("skipped")),
            "actions": ev.get("actions", []),
            "failed_count": len(failed_turns),
        }
    else:
        result["evolution"] = None
    (EVAL_RUNS / f"round{round_idx}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    s = summary
    print(f"  → 第{round_idx}轮汇总: 准确率 {s['accuracy']:.1%} | 总token {s['total_tokens']} | "
          f"平均 {s['avg_tokens_per_question']}/题 | ReAct {s['avg_react_rounds']}轮/题 | 耗时 {s['elapsed_total']:.0f}s")
    if result["evolution"]:
        ev = result["evolution"]
        if ev.get("skipped"):
            print(f"  → 进化: 未触发")
        else:
            print(f"  → 进化: {ev['mode']} 模式，失败{ev['failed_count']}条，执行 {len(ev['actions'])} 个动作")
    return result


# ── 对比与报告 ────────────────────────────────────────────────────────────────

def print_report(rounds: list[dict], versions: list[dict]):
    print("\n" + "=" * 78)
    print(f"  Skill 自进化实验报告（{len(rounds)} 轮 × {rounds[0]['summary']['total']} 题，混合主题，ReAct Agent + 真实 LLM）")
    print("=" * 78)
    print(f"  {'轮次':<8}{'Skill版':<10}{'准确率':<10}{'总token':<12}{'平均token/题':<14}{'平均ReAct':<10}{'平均耗时/题':<12}{'成本¥':<10}")
    print("-" * 78)
    for r in rounds:
        s = r["summary"]
        print(f"  第{s['round']}轮    v{s['skill_version']:<8}{s['accuracy']:.1%}{'':>4}"
              f"{s['total_tokens']:<12}{s['avg_tokens_per_question']:<14}"
              f"{s['avg_react_rounds']:<10}{s['avg_elapsed_per_question']}s{'':>4}{s['cost_estimate_yuan']:.4f}")
    print("-" * 78)

    r1, r4 = rounds[0]["summary"], rounds[-1]["summary"]
    print(f"  ▶ 优化前后对比（第1轮 v{r1['skill_version']} 初始版  →  第{len(rounds)}轮 v{r4['skill_version']} 最新版）:")
    print(f"    准确率:        {r1['accuracy']:.1%}  →  {r4['accuracy']:.1%}   ({r4['accuracy'] - r1['accuracy']:+.1%})")
    print(f"    总 token:      {r1['total_tokens']}  →  {r4['total_tokens']}   ({r4['total_tokens'] - r1['total_tokens']:+d})")
    print(f"    平均 token/题: {r1['avg_tokens_per_question']}  →  {r4['avg_tokens_per_question']}")
    print(f"    平均 ReAct 轮: {r1['avg_react_rounds']}  →  {r4['avg_react_rounds']}")
    print(f"    平均耗时/题:   {r1['avg_elapsed_per_question']}s  →  {r4['avg_elapsed_per_question']}s")
    print(f"    成本估算 ¥:    {r1['cost_estimate_yuan']:.4f}  →  {r4['cost_estimate_yuan']:.4f}")
    print("-" * 78)

    print("  ▶ Skill 版本进化链:")
    for v in versions:
        print(f"    v{v['version']} [{v['action']:<7}] {v['tokens']:>5} tokens  {v['time'][:19]}  {v['reason'][:48]}")
    print("-" * 78)

    print("  ▶ 各轮进化事件:")
    for r in rounds:
        ev = r["evolution"]
        s = r["summary"]
        if not ev:
            print(f"    第{s['round']}轮后: 未触发进化")
        elif ev.get("skipped"):
            print(f"    第{s['round']}轮后: 跳过（未触发）")
        else:
            print(f"    第{s['round']}轮后: {ev['mode']} 模式（失败{ev['failed_count']}条）→ 执行 {len(ev['actions'])} 个动作")
            for act in ev.get("actions", [])[:3]:
                print(f"        [{act['action']}] {act['reason'][:70]}")
    print("-" * 78)

    print("  ▶ 各轮准确率趋势:")
    for r in rounds:
        s = r["summary"]
        bar = "█" * int(s["accuracy"] * 20)
        print(f"    第{s['round']}轮 v{s['skill_version']}: {s['accuracy']:.1%} {bar}")
    print("-" * 78)

    print("  ▶ 逐题明细（各轮失败题目）:")
    for r in rounds:
        s = r["summary"]
        fails = [p for p in r["per_task"] if not p["correct"]]
        if fails:
            print(f"    第{s['round']}轮 失败 {len(fails)} 题:")
            for p in fails:
                print(f"      T{p['id']:02d} {p['title']}: {p['fail_reason'][:50]}")
        else:
            print(f"    第{s['round']}轮: 全部答对")
    print("=" * 78)


def main():
    parser = argparse.ArgumentParser(description="Skill 自进化实验（4 轮×20 题，混合主题）")
    parser.add_argument("--react-rounds", type=int, default=2, help="ReAct 最大循环轮数")
    args = parser.parse_args()

    if not os.getenv("DEEPSEEK_API_KEY"):
        print("错误: 请先设置环境变量 DEEPSEEK_API_KEY（export DEEPSEEK_API_KEY=\"sk-...\"）")
        sys.exit(1)

    # ── 准备：备份 + 还原 + 初始化 ────────────────────────────────────────────
    OUTPUTS.mkdir(exist_ok=True)
    sm = SkillManager(str(SKILLS_DIR), str(VERSIONS_DIR))
    ensure_original(sm)
    restore_from_original()
    sm = SkillManager(str(SKILLS_DIR), str(VERSIONS_DIR))
    for name, content in sm.load_all().items():
        sm._save_version(name, content, action="initial", reason="初始版（覆盖诗体体制基础与李白杜甫部分知识点）")

    # ── 加载 tasks.json（eval_set）和 demo_script.json（题目顺序） ────────────
    data = json.loads(TASKS.read_text(encoding="utf-8"))
    tasks_list = data["tasks"]
    tasks_by_id = {t["id"]: t for t in tasks_list}
    evaluator = Evaluator(tasks_list)
    optimizer = SkillOptimizer(sm)

    script_data = json.loads(DEMO_SCRIPT.read_text(encoding="utf-8"))
    demo_questions = script_data["questions"]
    nudge_interval = script_data["nudge_interval"]
    num_blocks = len(demo_questions) // nudge_interval

    # 按 demo_script 顺序构建分组，每组 nudge_interval 题（混合主题）
    groups = []
    for block_idx in range(num_blocks):
        block_questions = demo_questions[block_idx * nudge_interval:(block_idx + 1) * nudge_interval]
        block_tasks = [tasks_by_id[q["task_id"]] for q in block_questions]
        block_name = block_questions[0].get("block", f"block{block_idx + 1}")
        groups.append({"tasks": block_tasks, "name": block_name, "seq_range": f"seq{block_idx * nudge_interval + 1}-{(block_idx + 1) * nudge_interval}"})

    print(f"任务数: {len(tasks_list)} | 块数: {num_blocks} | 每块: {nudge_interval} 题 | ReAct 最大轮数: {args.react_rounds}")
    print(f"初始 Skill tokens: {_tokenize(sm.load_all().get('poetry_skill', ''))}")
    print(f"主题分布: 每块混合 唐诗/宋词/诗派典故/格律理论，确保与 Skill 已有知识重叠")

    # ── 8 块进化 ──────────────────────────────────────────────────────────────
    rounds = []
    for i in range(num_blocks):
        g = groups[i]
        print(f"\n[第{i + 1}块] {g['name']} | {g['seq_range']} | 用当前最新 Skill 回答 ...")
        agent = ReActCodingAgent(sm, evaluator, optimizer,
                                 max_react_rounds=args.react_rounds,
                                 nudge_interval=nudge_interval)
        result = run_round(agent, g["tasks"], i + 1, sm)
        result["block_name"] = g["name"]
        rounds.append(result)

    # ── 汇总与落盘 ────────────────────────────────────────────────────────────
    history = sm.get_version_history("poetry_skill")
    versions = [
        {"version": h["version"], "time": h["time"], "action": h["action"],
         "reason": h["reason"], "tokens": _tokenize(h["content"]),
         "snapshot_file": h.get("snapshot_file", "")}
        for h in history
    ]
    print_report(rounds, versions)

    log = {
        "generated_at": datetime.now().isoformat(),
        "config": {"num_blocks": num_blocks, "nudge_interval": nudge_interval,
                   "react_rounds": args.react_rounds,
                   "demo_script": str(DEMO_SCRIPT)},
        "rounds": [{"summary": r["summary"], "evolution": r["evolution"],
                     "block_name": r.get("block_name", "")} for r in rounds],
        "skill_versions": versions,
        "per_task": {f"block{r['summary']['round']}": r["per_task"] for r in rounds},
    }
    EVOL_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ evolution_log.json 已保存 ({EVOL_LOG})")
    print(f"✓ 逐块明细见 outputs/eval_runs/round{{1..{num_blocks}}}.json，各版本快照见 outputs/skill_snapshots/，skills/ 只保留最新版")


if __name__ == "__main__":
    main()
