# -*- coding: utf-8 -*-
"""
评估器：基于关键词匹配判断 Agent 回答是否正确。

零 LLM 成本的客观评估方案，ground truth 关键词选取自政策专有数字/术语，
LLM 在没有对应 Skill 时无法猜中这些词。

"""

import json
import re
from pathlib import Path
from collections import defaultdict


# 否定前缀：如果 forbidden 关键词前 NEG_WINDOW 字内出现这些字，视为被否定（不算命中）
NEG_PREFIXES = ("不", "无", "非", "未", "没")
NEG_WINDOW = 4

# 推脱硬信号：Agent 系统提示约定"不能回答时只说 '需要人工判定'"。
# 只要答案包含 "人工判定"，即判定为推脱失败（一票否决，不再看 required/forbidden）。
DEFERRAL_SIGNAL = "人工判定"


def _normalize(text: str) -> str:
    """匹配前归一化：数字千位分隔符一律去掉并小写化"""
    return re.sub(r"(?<=\d)[,，](?=\d)", "", text).lower()


def _forbidden_hits(text: str, keyword: str) -> bool:
    """
    检查 forbidden 关键词是否"真正"出现：
      - 若关键词前 NEG_WINDOW 字内有否定词，视为被否定，不算命中
      - 所有出现位置都被否定 -> 未命中；任一出现未被否定 -> 命中
    """
    idx = 0
    while True:
        pos = text.find(keyword, idx)
        if pos == -1:
            return False
        prefix = text[max(0, pos - NEG_WINDOW):pos]
        if not any(neg in prefix for neg in NEG_PREFIXES):
            return True
        idx = pos + 1


class Evaluator:
    def __init__(self, eval_set_path: str):
        data = json.loads(Path(eval_set_path).read_text(encoding="utf-8"))
        self.questions = {q["id"]: q for q in data["questions"]}

    def evaluate_answer(self, answer: str, question_id: int) -> tuple[bool, str]:
        """
        三种失败原因互斥，一票否决：
          1. "Agent 推脱"  — 答案含 DEFERRAL_SIGNAL
          2. "缺少关键词"  — required 有未出现的
          3. "出现禁止词"  — forbidden 有未被否定前置的命中
        """
        gt = self.questions[question_id]["ground_truth"]
        ans_norm = _normalize(answer)

        if DEFERRAL_SIGNAL in ans_norm:
            return False, f"Agent 推脱（含 '{DEFERRAL_SIGNAL}'）"

        for kw in gt.get("required", []):
            if _normalize(kw) not in ans_norm:
                return False, f"缺少关键词: '{kw}'"

        for kw in gt.get("forbidden", []):
            if _forbidden_hits(ans_norm, _normalize(kw)):
                return False, f"出现禁止词: '{kw}'"

        return True, "correct"

    def run_full_eval(self, agent_func, verbose: bool = False) -> dict:
        """
        对整个 eval_set 运行评估。
        agent_func: callable(question: str) -> str
        """
        total = 0
        correct = 0
        by_category = defaultdict(lambda: {"total": 0, "correct": 0})
        errors = []

        for qid, ques in sorted(self.questions.items()):
            answer = agent_func(ques["question"])
            ok, reason = self.evaluate_answer(answer, qid)
            total += 1
            by_category[ques["category"]]["total"] += 1
            if ok:
                correct += 1
                by_category[ques["category"]]["correct"] += 1
            else:
                errors.append({"id": qid, "category": ques["category"], "reason": reason,
                                "question": ques["question"][:40]})
                if verbose:
                    print(f"  x Q{qid} [{ques['category']}] {reason}")

        for cat in by_category.values():
            cat["accuracy"] = round(cat["correct"] / cat["total"], 3)

        return {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / total, 3),
            "by_category": dict(by_category),
            "errors": errors,
        }
