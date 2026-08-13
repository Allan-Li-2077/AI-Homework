from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.config import settings
from app.services import llm

INTENT_PROMPT = """你是意图分类器。根据用户问题判断意图，只输出 JSON，不要其他文字。

白名单公司（仅这些公司有年报知识库）：贵州茅台、五粮液、泸州老窖、习酒。

意图定义：
1. annual_report：询问白名单公司之一或多家的年报/财务数据/经营情况/营收利润分红等披露信息
2. other_report：询问非白名单公司的年报或财务披露，或明确要查其他上市公司年报
3. chitchat：与年报知识库无关的闲聊、常识、写作、编程等通用问题

输出格式：
{"intent":"annual_report|other_report|chitchat","companies":["贵州茅台"],"years":[2023],"need_rag":true}

规则：
- companies 只能填白名单内的标准名称；若问的是其他公司，intent 必须为 other_report，companies 为空数组
- years 从问题中提取 2022-2025，没有则空数组
- annual_report 时 need_rag=true；其他为 false
"""


@dataclass
class IntentResult:
    intent: str = "chitchat"
    companies: list[str] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    need_rag: bool = False


def _normalize_company(name: str) -> str | None:
    aliases = {
        "茅台": "贵州茅台",
        "贵州茅台": "贵州茅台",
        "茅台酒": "贵州茅台",
        "五粮液": "五粮液",
        "泸州老窖": "泸州老窖",
        "老窖": "泸州老窖",
        "习酒": "习酒",
        "贵州习酒": "习酒",
    }
    name = name.strip()
    if name in aliases:
        return aliases[name]
    for key, val in aliases.items():
        if key in name:
            return val
    return None


def _extract_years(question: str) -> list[int]:
    return sorted({int(m.group(0)) for m in re.finditer(r"202[2-5]", question)})


def _extract_companies(question: str) -> list[str]:
    q = question
    found: list[str] = []
    if "贵州茅台" in q or re.search(r"(?<!习)茅台", q):
        found.append("贵州茅台")
    if "五粮液" in q:
        found.append("五粮液")
    if "泸州老窖" in q or ("泸州" in q and "老窖" in q):
        found.append("泸州老窖")
    if "习酒" in q:
        found.append("习酒")
    return found


def _rule_based_intent(question: str) -> IntentResult | None:
    q = question.strip()
    report_keywords = [
        "年报",
        "年度报告",
        "营业收入",
        "营收",
        "净利润",
        "利润",
        "分红",
        "股息",
        "净资产",
        "资产负债",
        "财务",
        "主营业务",
        "经营活动",
        "现金流量",
        "每股收益",
        "ROE",
        "毛利率",
    ]
    other_companies = [
        "洋河",
        "山西汾酒",
        "汾酒",
        "古井贡",
        "水井坊",
        "张裕",
        "舍得",
        "酒鬼酒",
        "今世缘",
        "口子窖",
        "伊利",
        "招商银行",
        "宁德时代",
    ]

    companies = _extract_companies(q)
    years = _extract_years(q)
    mentions_other = any(x in q for x in other_companies)
    mentions_reportish = any(k in q for k in report_keywords)

    if mentions_other and (mentions_reportish or "年报" in q or "财务" in q):
        return IntentResult(intent="other_report", companies=[], years=years, need_rag=False)

    if companies and mentions_reportish:
        return IntentResult(
            intent="annual_report",
            companies=companies,
            years=years,
            need_rag=True,
        )

    if mentions_reportish and not companies and ("年报" in q or "上市公司" in q):
        return IntentResult(intent="other_report", companies=[], years=years, need_rag=False)

    if not mentions_reportish and not companies:
        return IntentResult(intent="chitchat", need_rag=False)

    return None


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no json")
    return json.loads(m.group(0))


def classify_intent(question: str) -> IntentResult:
    rule = _rule_based_intent(question)

    try:
        raw = llm.chat_text(
            [
                {"role": "system", "content": INTENT_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0,
        )
        data = _parse_json(raw)
        intent = data.get("intent", "chitchat")
        if intent not in {"annual_report", "other_report", "chitchat"}:
            intent = "chitchat"

        companies: list[str] = []
        for c in data.get("companies") or []:
            norm = _normalize_company(str(c))
            if norm and norm not in companies:
                companies.append(norm)

        years: list[int] = []
        for y in data.get("years") or []:
            try:
                yi = int(y)
                if 2022 <= yi <= 2025:
                    years.append(yi)
            except (TypeError, ValueError):
                pass
        if not years:
            years = _extract_years(question)

        if intent == "annual_report" and not companies:
            intent = "other_report"

        result = IntentResult(
            intent=intent,
            companies=companies,
            years=sorted(set(years)),
            need_rag=(intent == "annual_report"),
        )

        if rule and rule.intent == "other_report":
            return rule
        if rule and rule.intent == "annual_report" and not result.companies:
            return rule
        return result
    except Exception:
        if rule:
            return rule
        return IntentResult(intent="chitchat", need_rag=False)
