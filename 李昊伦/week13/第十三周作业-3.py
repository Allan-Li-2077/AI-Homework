"""
触发匹配器 — 两阶段渐进式匹配

阶段 1：关键词预筛（零 token 消耗）
  - 从 skill description 提取关键词
  - 检查用户输入是否命中
  - 返回候选列表

阶段 2：LLM 确认（仅在有候选时调用）
  - 只把候选 skill 的 name + description 发给 LLM
  - LLM 选择最匹配的 skill 或返回 none
"""

from __future__ import annotations

import re
from openai import OpenAI
from src.skill_registry import SkillIndex


# ── 阶段 1：关键词预筛 ─────────────────────────────────────────

def _extract_keywords(description: str) -> list[str]:
    """从 description 中提取触发关键词"""
    keywords = set()
    # 中文关键词：2-6 字的连续中文
    for m in re.findall(r"[一-鿿]{2,6}", description):
        keywords.add(m)
    # 英文单词（3 字母以上）
    for m in re.findall(r"\b[a-zA-Z]{3,}\b", description):
        keywords.add(m.lower())
    # 英文词组（如 flash card, flow chart）
    for m in re.findall(r"\b[a-zA-Z]+ [a-zA-Z]+\b", description):
        keywords.add(m.lower())
    return list(keywords)


def keyword_filter(user_input: str, skills: list[SkillIndex]) -> list[SkillIndex]:
    """阶段 1：关键词预筛，返回候选 skill 列表"""
    candidates = []
    user_lower = user_input.lower()
    for skill in skills:
        keywords = _extract_keywords(skill.description)
        for kw in keywords:
            if kw in user_lower:
                candidates.append(skill)
                break
    return candidates


# ── 阶段 2：LLM 确认 ──────────────────────────────────────────

MATCH_SYSTEM_PROMPT = """你是一个 Skill 匹配器。根据用户输入，从候选 Skill 列表中选择最匹配的一个。

规则：
- 只从候选列表中选择，不要编造
- 如果没有匹配的，返回 "none"
- 只返回 skill 的 name，不要多余文字"""


def build_match_prompt(candidates: list[SkillIndex], user_input: str) -> str:
    """构建 LLM 匹配 prompt（只含触发层信息）"""
    skill_list = "\n".join(
        f"- {s.name}: {s.trigger_hint}" for s in candidates
    )
    return f"""候选 Skills：
{skill_list}

用户输入：{user_input}

请返回最匹配的 skill name，或 "none"："""


def llm_confirm(
    client: OpenAI,
    model: str,
    user_input: str,
    candidates: list[SkillIndex],
) -> SkillIndex | None:
    """阶段 2：LLM 确认最匹配的 skill"""
    if not candidates:
        return None

    # 只有 1 个候选，直接返回（省一次 LLM 调用）
    if len(candidates) == 1:
        return candidates[0]

    # 多个候选，调用 LLM 选择
    prompt = build_match_prompt(candidates, user_input)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": MATCH_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=50,
        )
        answer = resp.choices[0].message.content.strip().lower()
        for s in candidates:
            if s.name.lower() in answer:
                return s
    except Exception:
        pass
    return None


def match_skill(
    client: OpenAI,
    model: str,
    user_input: str,
    skills: list[SkillIndex],
) -> SkillIndex | None:
    """完整两阶段匹配流程"""
    # 阶段 1：关键词预筛
    candidates = keyword_filter(user_input, skills)
    if not candidates:
        return None

    # 阶段 2：LLM 确认
    return llm_confirm(client, model, user_input, candidates)
