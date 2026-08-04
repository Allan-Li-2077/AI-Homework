from __future__ import annotations

import math
import re
from collections import Counter

from .models import MatchResult, SkillMetadata


TOKEN_RE = re.compile(r"[a-zA-Z0-9_+-]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    # 一个很轻量的分词器：英文按单词切，中文按单字切。
    # 对 demo harness 来说足够直观；生产环境可以换成 BM25/向量检索。
    return [m.group(0).lower() for m in TOKEN_RE.finditer(text or "")]


class SkillMatcher:
    def rank(self, request: str, skills: list[SkillMetadata]) -> list[MatchResult]:
        # 提示：这里做的是“先粗选”。
        # 只用 skill 名称和 description 计算分数，不读取完整 SKILL.md。
        query = tokenize(request)
        if not query:
            return []
        query_counts = Counter(query)
        docs = [tokenize(f"{s.name} {s.description}") for s in skills]
        df = Counter(token for doc in docs for token in set(doc))
        total_docs = max(1, len(docs))

        results: list[MatchResult] = []
        for skill, doc in zip(skills, docs, strict=True):
            doc_counts = Counter(doc)
            score = 0.0
            reasons: list[str] = []
            for token, q_count in query_counts.items():
                if token not in doc_counts:
                    continue
                # 中文单字命中很容易产生噪声，所以降低权重。
                token_weight = 0.15 if _is_single_cjk(token) else 1.0
                idf = math.log((total_docs + 1) / (df[token] + 0.5)) + 1
                score += q_count * doc_counts[token] * idf * token_weight
                if len(reasons) < 5 and not _is_single_cjk(token):
                    reasons.append(token)

            score += self._keyword_boost(request, skill, reasons)
            if score > 0:
                results.append(MatchResult(skill=skill, score=round(score, 3), reasons=tuple(reasons)))

        return sorted(results, key=lambda r: r.score, reverse=True)

    def _keyword_boost(self, request: str, skill: SkillMetadata, reasons: list[str]) -> float:
        # 示例补一点领域关键词加权，让 flash card / diagram 的匹配更稳定。
        text = request.lower()
        name = skill.name.lower()
        boost = 0.0
        flash_terms = ("flash card", "flashcard", "card", "闪卡", "单词卡", "单词")
        diagram_terms = ("diagram", "flowchart", "sequence", "架构图", "流程图", "时序图", "结构图", "画图", "图表")

        if name == "flash-card" and any(term in text for term in flash_terms):
            boost += 4.0
            reasons.append("flash-card keyword")
        if name == "baoyu-diagram" and any(term in text for term in diagram_terms):
            boost += 4.0
            reasons.append("diagram keyword")
        return boost


def _is_single_cjk(token: str) -> bool:
    return len(token) == 1 and "\u4e00" <= token <= "\u9fff"
