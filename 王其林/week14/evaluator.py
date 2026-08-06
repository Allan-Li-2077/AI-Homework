"""
评估器：关键词匹配 + 文本契约检查（零 LLM 成本，规则确定性）。

设计（沿用参考项目"契约式评估"思路）：
  - Skill 输出契约：任务回答须为完整文本（无需代码块），关键知识点必须覆盖
  - 评估规则（互斥失败原因）：
      1. 推脱          — 回答含"无法回答/抱歉/不清楚"等信号
      2. 缺少关键词     — required 中有未出现的
      3. 出现禁止词     — forbidden 中有未被否定前置的命中
    全部通过才判对。
  - required/forbidden 关键词均取自任务的标准答案要点（如静夜思、李白、
    东坡居士、念奴娇、大江东去、豪放派、诗经六义等），答对必然命中、答偏难以碰巧。
  - 归一化：小写 + 去千位分隔符；否定前置检测避免"不使用UIWebView"误伤 forbidden。
"""

import re

# 推脱信号（Agent 契约：会就答、不会就明说）
DEFERRAL_SIGNALS = ("无法回答", "无法提供", "无法作答", "不能回答", "不能提供", "抱歉", "很抱歉", "不清楚", "技能文档未涵盖", "未涵盖此知识点")

# 否定前缀：forbidden 关键词前 NEG_WINDOW 字内出现这些字 → 视为被否定，不算命中
NEG_PREFIXES = ("不", "无", "非", "未", "没", "禁止", "不能", "不要")
NEG_WINDOW = 6


def _normalize(text: str) -> str:
    """归一化：去数字间千位分隔符 + 小写化"""
    return re.sub(r"(?<=\d)[,，](?=\d)", "", text).lower()


def _forbidden_hits(text: str, keyword: str) -> bool:
    """forbidden 关键词是否"真正"出现（未被否定前置）"""
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
    def __init__(self, tasks: list[dict]):
        self.tasks = {t["id"]: t for t in tasks}

    def evaluate_answer(self, answer: str, task: dict) -> tuple[bool, str]:
        """返回 (是否正确, 失败原因)。task 为任务 dict（含 required / forbidden）。"""
        if "技能文档未涵盖" in answer or "未涵盖此知识点" in answer:
            return False, "技能文档未覆盖此知识点（需 patch 扩展该类知识点）"
        if any(s in answer for s in DEFERRAL_SIGNALS):
            return False, "推脱（拒绝回答）"

        norm = _normalize(answer)

        for kw in task.get("required", []):
            if _normalize(kw) not in norm:
                # 故意不透露具体缺失关键词：避免 ReAct 第二轮直接"照抄"修正，
                # 让 Agent 必须自行判断遗漏，从而为 Skill 进化留出真实的失败样本。
                return False, "回答不完整：缺少部分关键知识点（请对照任务要求，补充遗漏的具体术语/方法名/流程步骤）"

        for kw in task.get("forbidden", []):
            if _forbidden_hits(norm, _normalize(kw)):
                return False, f"出现禁止词: '{kw}'"

        return True, "correct"

    def run_eval(self, answers: dict[int, str]) -> dict:
        """给定 {task_id: answer}，批量评估并汇总。"""
        total, correct = 0, 0
        details = []
        for tid, ans in answers.items():
            task = self.tasks[tid]
            ok, reason = self.evaluate_answer(ans, task)
            total += 1
            correct += int(ok)
            details.append({"id": tid, "title": task["title"], "correct": ok,
                            "fail_reason": reason if not ok else ""})
        return {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / total, 4) if total else 0,
            "details": details,
        }
