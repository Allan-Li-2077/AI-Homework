"""
多维度评估器：对 Agent 回答进行准确率 + 完整性 + 冗余度三维评估。

设计思路（与参考项目 evaluator.py 的差异）：
  - 参考项目：纯关键词匹配，返回 pass/fail 二元结果
  - 本项目：多维度打分，每题给出 score(0-100) + 失败原因列表
  - 增加回答长度统计（衡量 Agent 是否啰嗦）

评估维度：
  1. 完整性（must_include 覆盖率）：关键信息是否都提到了
  2. 准确性（must_exclude 违规检测）：有没有说错误信息
  3. 冗余度（回答字符数）：Agent 回答是否过于啰嗦
"""

import json
import re
from pathlib import Path
from collections import defaultdict


def _normalize(text: str) -> str:
    """归一化：去千位分隔符 + 小写"""
    return re.sub(r"(?<=\d)[,，](?=\d)", "", text).lower()


class TravelEvaluator:

    def __init__(self, eval_set_path: str):
        data = json.loads(Path(eval_set_path).read_text(encoding="utf-8"))
        self.questions = {q["id"]: q for q in data["questions"]}
        self.meta = data.get("meta", {})

    def evaluate_one(self, answer: str, qid: int) -> dict:
        """
        评估单个回答，返回：
        {
            "score": 0-100,
            "passed": bool,
            "failures": ["原因1", "原因2", ...],
            "include_hit_rate": 0.0-1.0,  # must_include 命中率
            "exclude_violations": int,       # must_exclude 违规数
        }
        """
        q = self.questions[qid]
        ans_norm = _normalize(answer)
        failures = []

        # 1. 检查 must_include
        must_include = q.get("must_include", [])
        include_hits = 0
        for kw in must_include:
            if _normalize(kw) in ans_norm:
                include_hits += 1
            else:
                failures.append(f"缺少关键信息: '{kw}'")
        include_rate = include_hits / max(len(must_include), 1)

        # 2. 检查 must_exclude
        must_exclude = q.get("must_exclude", [])
        exclude_violations = 0
        for kw in must_exclude:
            if _normalize(kw) in ans_norm:
                exclude_violations += 1
                failures.append(f"包含错误信息: '{kw}'")

        # 3. 计算综合分数
        #    - 完整性占 60 分（按命中率）
        #    - 准确性占 40 分（无违规=满分，有违规则扣分）
        score_include = include_rate * 60
        score_exclude = max(0, 40 - exclude_violations * 20)
        score = round(score_include + score_exclude)
        passed = (score >= 80)  # 80 分及以上算通过

        return {
            "score": score,
            "passed": passed,
            "failures": failures,
            "include_hit_rate": round(include_rate, 3),
            "exclude_violations": exclude_violations,
        }

    def run_eval(self, agent) -> dict:
        """
        对全部问题运行评估，返回汇总结果：
        {
            "total_questions": int,
            "passed_count": int,
            "pass_rate": float,
            "avg_score": float,
            "by_category": {cat: {passed, total, pass_rate, avg_score}},
            "details": [{qid, category, question, answer, score, passed, failures, ...}],
            "agent_stats": {...},
        }
        """
        agent.reset_stats()
        details = []
        by_cat = defaultdict(lambda: {"passed": 0, "total": 0, "scores": []})

        for qid, q in sorted(self.questions.items()):
            result = agent.answer(q["question"])
            eval_result = self.evaluate_one(result["answer"], qid)
            cat = q["category"]

            by_cat[cat]["total"] += 1
            by_cat[cat]["scores"].append(eval_result["score"])
            if eval_result["passed"]:
                by_cat[cat]["passed"] += 1

            details.append({
                "qid": qid,
                "category": cat,
                "question": q["question"],
                "answer": result["answer"],
                "score": eval_result["score"],
                "passed": eval_result["passed"],
                "failures": eval_result["failures"],
                "include_hit_rate": eval_result["include_hit_rate"],
                "prompt_tokens": result["prompt_tokens"],
                "completion_tokens": result["completion_tokens"],
                "time_sec": result["time_sec"],
                "answer_chars": result["answer_chars"],
            })

        # 分类汇总
        for cat in by_cat.values():
            cat["pass_rate"] = round(cat["passed"] / cat["total"], 3)
            cat["avg_score"] = round(sum(cat["scores"]) / cat["total"], 1)
            del cat["scores"]

        passed_count = sum(1 for d in details if d["passed"])
        total = len(details)
        avg_score = round(sum(d["score"] for d in details) / total, 1) if total else 0

        return {
            "total_questions": total,
            "passed_count": passed_count,
            "pass_rate": round(passed_count / total, 3) if total else 0,
            "avg_score": avg_score,
            "by_category": dict(by_cat),
            "details": details,
            "agent_stats": agent.stats(),
        }

    def print_report(self, result: dict, title: str = "评估报告"):
        """打印可读的评估报告"""
        print(f"\n{'═' * 64}")
        print(f"  {title}")
        print(f"{'═' * 64}")
        print(f"  通过率:  {result['passed_count']}/{result['total_questions']} = {result['pass_rate']:.0%}")
        print(f"  平均分:  {result['avg_score']}")

        print(f"\n  ┌─ 分类统计 ──────────────────────────────────────────┐")
        for cat, s in sorted(result["by_category"].items()):
            bar = "█" * int(s["pass_rate"] * 20)
            print(f"  │ {cat:<12} {s['passed']:>2}/{s['total']:>2} 通过率{s['pass_rate']:.0%}  均分{s['avg_score']:.0f}  {bar:<20}│")
        print(f"  └─────────────────────────────────────────────────────┘")

        st = result["agent_stats"]
        print(f"\n  ┌─ Token 消耗 ────────────────────────────────────────┐")
        print(f"  │  调用次数:       {st['calls']:<40}│")
        print(f"  │  总 token:       {st['total_tokens']:<40}│")
        print(f"  │    prompt:       {st['prompt_tokens']:<40}│")
        print(f"  │    completion:   {st['completion_tokens']:<40}│")
        print(f"  │  平均 prompt/次: {st['avg_prompt_tokens']:<40}│")
        print(f"  │  总耗时:         {st['total_time']}s{' ' * (37 - len(str(st['total_time'])))}│")
        print(f"  │  平均耗时/次:    {st['avg_time']}s{' ' * (37 - len(str(st['avg_time'])))}│")
        print(f"  └─────────────────────────────────────────────────────┘")

        # 打印失败详情
        failed = [d for d in result["details"] if not d["passed"]]
        if failed:
            print(f"\n  未通过题目 ({len(failed)} 题):")
            for d in failed[:5]:
                print(f"    Q{d['qid']:02d} [{d['category']}] {d['question'][:40]}")
                for f in d["failures"][:2]:
                    print(f"         → {f}")
