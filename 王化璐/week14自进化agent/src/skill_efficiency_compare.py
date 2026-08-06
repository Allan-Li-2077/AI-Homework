"""
Skill 效率对比脚本：用当前 skills/ 目录下的 Skill 跑 60 题评估，
记录每题的 token 消耗（input/output/total），输出统计报告。

用法：
  $env:DEEPSEEK_API_KEY="你的key"
  python src/skill_efficiency_compare.py --label bloated
  python src/skill_efficiency_compare.py --label optimized
"""
import os, sys, json, time, argparse
from pathlib import Path
from datetime import datetime
from openai import OpenAI

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from skill_manager import SkillManager
from evaluator import Evaluator

SYSTEM_TEMPLATE = """你是铁力健身俱乐部的会员客服助手。

你的所有知识来源于以下技能文档，严格基于文档内容回答，不要自行推断或编造政策。

## 回答规则（严格遵守）
- 【能回答】如果技能文档覆盖了用户问题：直接给出完整具体的答案（含具体天数/金额/
  工作日数等政策细节）。**不要在答案中加"建议联系人工客服"之类的推脱话**。
- 【不能回答】如果技能文档确实不覆盖：**仅回答一句** "需要联系人工客服"，
  不要编造答案，也不要列举可能的情况。

{skills_section}
"""

SKILLS_SECTION_TEMPLATE = """## 当前知识库（共{count}个技能）

{skills_content}
"""


def build_system_prompt(sm: SkillManager) -> str:
    skills = sm.load_all()
    if not skills:
        skills_section = "（暂无技能文档，请依据通用客服原则回答）"
    else:
        parts = []
        for name, content in sorted(skills.items()):
            parts.append(f"### 技能：{name}\n{content}")
        skills_content = "\n\n---\n\n".join(parts)
        skills_section = SKILLS_SECTION_TEMPLATE.format(
            count=len(skills),
            skills_content=skills_content,
        )
    return SYSTEM_TEMPLATE.format(skills_section=skills_section)


def run_evaluation(label: str):
    sm = SkillManager(str(ROOT / "skills"), str(ROOT / "outputs" / "skill_versions"))
    ev = Evaluator(str(ROOT / "data" / "eval_set.json"))
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )

    # 构建 system prompt 并计算其字符数
    system_prompt = build_system_prompt(sm)
    skill_chars = len(system_prompt)

    skills_loaded = sm.load_all()
    print(f"\n{'='*60}")
    print(f"  Skill 效率对比 - [{label}]")
    print(f"{'='*60}")
    print(f"  Skills: {list(skills_loaded.keys())}")
    print(f"  Skill 文件数: {len(skills_loaded)}")
    print(f"  System prompt 字符数: {skill_chars}")
    print(f"  评估题目数: {len(ev.questions)}")
    print(f"{'='*60}\n")

    results = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    correct = 0
    by_cat = {}

    for qid in sorted(ev.questions.keys()):
        q = ev.questions[qid]
        question = q["question"]

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=400,
        )

        answer = response.choices[0].message.content.strip()
        usage = response.usage

        prompt_tokens = usage.prompt_tokens
        completion_tokens = usage.completion_tokens
        tokens = usage.total_tokens

        total_prompt_tokens += prompt_tokens
        total_completion_tokens += completion_tokens
        total_tokens += tokens

        ok, reason = ev.evaluate_answer(answer, qid)
        if ok:
            correct += 1

        cat = q["category"]
        by_cat.setdefault(cat, {"total": 0, "correct": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        by_cat[cat]["total"] += 1
        if ok:
            by_cat[cat]["correct"] += 1
        by_cat[cat]["prompt_tokens"] += prompt_tokens
        by_cat[cat]["completion_tokens"] += completion_tokens
        by_cat[cat]["total_tokens"] += tokens

        mark = "✓" if ok else "✗"
        print(f"Q{qid:02d} {mark} [{cat:<22}] pt={prompt_tokens:>5} ct={completion_tokens:>4} tt={tokens:>5}  {question[:40]}")

        results.append({
            "id": qid,
            "category": cat,
            "question": question,
            "answer": answer,
            "ground_truth": q["ground_truth"],
            "correct": ok,
            "reason": reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": tokens,
            "answer_length": len(answer),
        })

    n = len(ev.questions)
    accuracy = correct / n

    print(f"\n{'='*60}")
    print(f"  [{label}] 评估结果")
    print(f"{'='*60}")
    print(f"  准确率:              {correct}/{n} = {accuracy:.1%}")
    print(f"  总 input tokens:     {total_prompt_tokens:,}")
    print(f"  总 output tokens:    {total_completion_tokens:,}")
    print(f"  总 tokens:           {total_tokens:,}")
    print(f"  平均每题 input:      {total_prompt_tokens/n:.0f}")
    print(f"  平均每题 output:     {total_completion_tokens/n:.0f}")
    print(f"  平均每题 total:      {total_tokens/n:.0f}")
    print(f"  System prompt 字符:  {skill_chars}")
    print(f"  Skill 文件数:        {len(skills_loaded)}")
    print(f"\n  分类统计:")
    for cat in sorted(by_cat):
        s = by_cat[cat]
        acc = s["correct"] / s["total"]
        print(f"    {cat:<22} {s['correct']:>2}/{s['total']:>2} {acc:>5.0%}  "
              f"pt={s['prompt_tokens']:>5} ct={s['completion_tokens']:>4} tt={s['total_tokens']:>5}")
    print(f"{'='*60}\n")

    # 保存结果
    out = ROOT / "outputs" / f"efficiency_compare_{label}.json"
    out.write_text(json.dumps({
        "label": label,
        "timestamp": datetime.now().isoformat(),
        "skill_names": list(skills_loaded.keys()),
        "skill_file_count": len(skills_loaded),
        "system_prompt_chars": skill_chars,
        "summary": {
            "accuracy": round(accuracy, 4),
            "correct": correct,
            "total_questions": n,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "avg_prompt_tokens": round(total_prompt_tokens / n, 1),
            "avg_completion_tokens": round(total_completion_tokens / n, 1),
            "avg_total_tokens": round(total_tokens / n, 1),
        },
        "by_category": by_cat,
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 结果已保存到 {out}")

    return {
        "label": label,
        "accuracy": accuracy,
        "correct": correct,
        "total": n,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "avg_prompt_tokens": round(total_prompt_tokens / n, 1),
        "avg_completion_tokens": round(total_completion_tokens / n, 1),
        "avg_total_tokens": round(total_tokens / n, 1),
        "system_prompt_chars": skill_chars,
        "skill_file_count": len(skills_loaded),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Skill 效率对比评估")
    parser.add_argument("--label", type=str, required=True, help="标签名：bloated 或 optimized")
    args = parser.parse_args()

    summary = run_evaluation(args.label)

    # 如果两个结果都存在，打印对比
    bloated_path = ROOT / "outputs" / "efficiency_compare_bloated.json"
    optimized_path = ROOT / "outputs" / "efficiency_compare_optimized.json"

    if bloated_path.exists() and optimized_path.exists():
        b = json.loads(bloated_path.read_text(encoding="utf-8"))["summary"]
        o = json.loads(optimized_path.read_text(encoding="utf-8"))["summary"]

        print(f"\n{'='*60}")
        print(f"  优化前后对比报告")
        print(f"{'='*60}")
        print(f"{'指标':<24} {'臃肿版':>12} {'优化版':>12} {'差异':>12}")
        print(f"{'-'*60}")
        print(f"{'准确率':<24} {b['accuracy']:>11.1%} {o['accuracy']:>11.1%} {o['accuracy']-b['accuracy']:>+11.1%}")
        print(f"{'总 input tokens':<24} {b['total_prompt_tokens']:>12,} {o['total_prompt_tokens']:>12,} {o['total_prompt_tokens']-b['total_prompt_tokens']:>+12,}")
        print(f"{'总 output tokens':<24} {b['total_completion_tokens']:>12,} {o['total_completion_tokens']:>12,} {o['total_completion_tokens']-b['total_completion_tokens']:>+12,}")
        print(f"{'总 tokens':<24} {b['total_tokens']:>12,} {o['total_tokens']:>12,} {o['total_tokens']-b['total_tokens']:>+12,}")
        print(f"{'平均每题 input':<24} {b['avg_prompt_tokens']:>12.0f} {o['avg_prompt_tokens']:>12.0f} {o['avg_prompt_tokens']-b['avg_prompt_tokens']:>+12.0f}")
        print(f"{'平均每题 output':<24} {b['avg_completion_tokens']:>12.0f} {o['avg_completion_tokens']:>12.0f} {o['avg_completion_tokens']-b['avg_completion_tokens']:>+12.0f}")
        print(f"{'平均每题 total':<24} {b['avg_total_tokens']:>12.0f} {o['avg_total_tokens']:>12.0f} {o['avg_total_tokens']-b['avg_total_tokens']:>+12.0f}")

        b_chars = bloated_path.parent.parent / "skills"
        # 也打印 system prompt 字符数对比
        b_full = json.loads(bloated_path.read_text(encoding="utf-8"))
        o_full = json.loads(optimized_path.read_text(encoding="utf-8"))
        print(f"{'System prompt 字符数':<24} {b_full['system_prompt_chars']:>12,} {o_full['system_prompt_chars']:>12,} {o_full['system_prompt_chars']-b_full['system_prompt_chars']:>+12,}")
        print(f"{'Skill 文件数':<24} {b_full['skill_file_count']:>12} {o_full['skill_file_count']:>12} {o_full['skill_file_count']-b_full['skill_file_count']:>+12}")
        print(f"{'='*60}\n")
