from __future__ import annotations

from dataclasses import dataclass
import re

from .models import SkillMeta


@dataclass(frozen=True)
class RouteCandidate:
    skill: SkillMeta
    score: float
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return {"skill": self.skill.name, "score": self.score, "reasons": list(self.reasons)}


class SkillRouter:
    """Metadata-only router."""

    def __init__(self, skills: list[SkillMeta]):
        self.skills = skills

    def route(self, request: str, *, top_k: int = 3) -> list[RouteCandidate]:
        request_l = request.lower()
        words = _latin_tokens(request_l)
        grams = _cjk_ngrams(request)
        candidates: list[RouteCandidate] = []
        for skill in self.skills:
            haystack = f"{skill.name}\n{skill.description}".lower()
            score = 0.0
            reasons: list[str] = []
            if skill.name.lower() in request_l:
                score += 100
                reasons.append("request mentions skill name")
            for word in words:
                if word in haystack:
                    score += 6
                    reasons.append(f"keyword:{word}")
            for gram in grams:
                if gram in haystack:
                    score += min(8, 1 + len(gram) * 0.8)
                    if len(reasons) < 8:
                        reasons.append(f"短语:{gram}")
            score += _domain_bonus(request_l, haystack)
            if score > 0:
                candidates.append(RouteCandidate(skill=skill, score=round(score, 2), reasons=_dedupe(reasons)))
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:top_k]

    def select(self, request: str, *, explicit_skill: str | None = None) -> RouteCandidate | None:
        if explicit_skill:
            lowered = explicit_skill.lower()
            for skill in self.skills:
                if skill.name.lower() == lowered or skill.skill_dir.name.lower() == lowered:
                    return RouteCandidate(skill=skill, score=999, reasons=["explicit skill"])
            return None
        candidates = self.route(request, top_k=1)
        return candidates[0] if candidates else None


def _latin_tokens(text: str) -> set[str]:
    stop = {"the", "a", "an", "to", "for", "of", "and", "or", "me", "make", "create", "draw", "give", "with"}
    return {t for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{1,}", text) if t not in stop}


def _cjk_ngrams(text: str) -> set[str]:
    grams: set[str] = set()
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        n = len(segment)
        for size in range(2, min(7, n) + 1):
            for i in range(0, n - size + 1):
                grams.add(segment[i : i + size])
    return grams


def _domain_bonus(request_l: str, haystack: str) -> float:
    bonus = 0.0
    flash_terms = ["闪卡", "单词卡", "flash card", "flashcard", "音标", "例句"]
    diagram_terms = ["图表", "架构图", "流程图", "时序图", "画个图", "diagram", "flowchart", "sequence"]
    weekly_terms = ["周报", "写周报", "生成周报", "weekly report", "weekly update", "work summary", "本周"]
    html_terms = ["html", "页面", "网页", "landing page", "dashboard", "report page", "static ui", "web page"]
    if any(t in request_l for t in flash_terms) and any(t in haystack for t in flash_terms):
        bonus += 20
    if any(t in request_l for t in diagram_terms) and any(t in haystack for t in diagram_terms):
        bonus += 20
    if any(t in request_l for t in weekly_terms) and any(t in haystack for t in weekly_terms):
        bonus += 20
    if any(t in request_l for t in html_terms) and any(t in haystack for t in html_terms):
        bonus += 20
    return bonus


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item not in out:
            out.append(item)
    return out
