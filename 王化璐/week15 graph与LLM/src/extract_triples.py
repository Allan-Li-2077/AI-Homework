"""
求职公司调研 - 三元组抽取（LLM 驱动）
参考 graphrag_financial_report 项目，Schema 改成求职场景
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field

# 让脚本也能单独跑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import llm_client

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)
TRIPLES_JSON = os.path.join(OUTPUT_DIR, "company_triples.json")

# ============================================================
# 求职场景的 Schema：7 种实体类型 + 7 种关系类型
# ============================================================
ENTITY_TYPES = {
    "Company",          # 公司本体（字节跳动、商汤科技...）
    "BusinessSegment",  # 业务板块（短视频、AI大模型、云计算...）
    "SalaryIndicator",  # 薪资指标（应届生年薪30w、年终奖3月...）
    "TechnologyStack",  # 技术栈（Go、PyTorch、Kubernetes、Rust...）
    "Person",           # 核心人物（梁汝波、汤晓鸥...）
    "Industry",         # 行业/赛道（短视频、人工智能、自动驾驶...）
    "InterviewProcess", # 面试环节（笔试、技术一面、交叉面、HR面...）
}

RELATION_TYPES = {
    "OPERATES_IN",      # Company -OPERATES_IN-> BusinessSegment     公司经营某业务
    "REPORTS",          # Company -REPORTS-> SalaryIndicator          公司薪资待遇（边带 year/role 属性）
    "USES_TECH",        # Company -USES_TECH-> TechnologyStack        公司使用某技术
    "SERVES_AS",        # Person -SERVES_AS(CEO/CTO)-> Company        人物在公司任某职位
    "BELONGS_TO",       # Company -BELONGS_TO-> Industry              公司属于某行业
    "HAS_PROCESS",      # Company -HAS_PROCESS-> InterviewProcess     公司某面试流程（边带 order 属性）
    "HAS_PERSON",       # Company -HAS_PERSON-> Person                公司有某高管/创始人（反向用，可选）
}

SYSTEM_PROMPT = f"""你是一名求职调研数据工程师，负责从非结构化文本中抽取结构化三元组存入知识图谱。

【实体类型 Entity Types】——共 {len(ENTITY_TYPES)} 种：
{json.dumps(sorted(ENTITY_TYPES), ensure_ascii=False, indent=2)}

【关系类型 Relation Types】——共 {len(RELATION_TYPES)} 种，方向为 主语→宾语：
{json.dumps(sorted(RELATION_TYPES), ensure_ascii=False, indent=2)}

【抽取要求】
1. 仅从原文内容抽取，不要脑补、不要概括。
2. 严格使用上述实体/关系枚举，不得自创新类型。
3. 主语和宾语必须是具体名词（姓名、金额、技术名、公司名…），不得是抽象概念。
4. SalaryIndicator 是一个宾语节点，描述具体的薪资档位：例如 "2024年算法岗应届生base35w×15薪"、"后端校招SP 年薪40w"；不要把数字单独当节点。
5. InterviewProcess 是具体环节名：例如 "在线笔试"、"技术一面"、"交叉面"、"HR谈薪"；Company 通过 HAS_PROCESS 连接，边属性 order 标顺序（数字 1..N）。
6. RELATIONS 每一项是一个对象：{{"subject": str, "subject_type": str, "relation": str, "object": str, "object_type": str, "attributes": {{}}}}。
   - attributes 中可放 year / role / order / source 等补充信息，没有就留 {{}}。
   - attributes 内的数字如果是数量/金额/年份，保留数字类型，其余一律字符串。

【严格 JSON 输出】：
{{
  "entities": [
    {{"name": "字节跳动", "type": "Company"}},
    {{"name": "抖音", "type": "BusinessSegment"}}
  ],
  "relations": [
    {{"subject": "字节跳动", "subject_type": "Company", "relation": "OPERATES_IN", "object": "抖音", "object_type": "BusinessSegment", "attributes": {{}}}}
  ]
}}

只输出 JSON，不要任何解释文字、不要 Markdown 代码块。
"""


@dataclass
class TripleBatch:
    source: str                               # 来源（公司名+侧面标签，如 "字节跳动_业务"）
    entities: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    raw_text_len: int = 0
    llm_calls: int = 0
    elapsed_ms: int = 0

    def to_dict(self):
        return {
            "source": self.source,
            "entities": self.entities,
            "relations": self.relations,
            "raw_text_len": self.raw_text_len,
            "llm_calls": self.llm_calls,
            "elapsed_ms": self.elapsed_ms,
        }


def extract_from_text(source_label: str, text: str) -> TripleBatch:
    """
    给定一段文本（某家公司某侧面的调研总结），让 LLM 抽出三元组。
    """
    t0 = time.perf_counter()
    batch = TripleBatch(source=source_label, raw_text_len=len(text))

    user_msg = f"""【源文本】
{text[:12000]}

请从以上文本抽取实体和三元组，严格按系统提示的 JSON 格式输出。"""

    data = llm_client.chat_structured_json([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ], temperature=0.1, max_tokens=4096)
    batch.llm_calls = 1

    entities = data.get("entities") or []
    relations = data.get("relations") or []

    # 校验过滤：非法 entity_type / relation 直接丢弃
    valid_ents = []
    for e in entities:
        if e.get("type") in ENTITY_TYPES and e.get("name"):
            valid_ents.append({"name": str(e["name"]).strip(), "type": e["type"]})
    batch.entities = valid_ents

    valid_rels = []
    for r in relations:
        if (r.get("subject") and r.get("object")
                and r.get("relation") in RELATION_TYPES
                and r.get("subject_type") in ENTITY_TYPES
                and r.get("object_type") in ENTITY_TYPES):
            valid_rels.append({
                "subject": str(r["subject"]).strip(),
                "subject_type": r["subject_type"],
                "relation": r["relation"],
                "object": str(r["object"]).strip(),
                "object_type": r["object_type"],
                "attributes": r.get("attributes") or {},
            })
    batch.relations = valid_rels
    batch.elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return batch


def save_triples(batches: list[TripleBatch], path: str = TRIPLES_JSON):
    """把多批次三元组追加到总 JSON 文件（幂等：按 source 去重）"""
    existing = []
    if os.path.exists(path):
        try:
            existing = json.load(open(path, "r", encoding="utf-8"))
        except Exception:
            existing = []
    seen = {b.get("source") for b in existing}
    for b in batches:
        if b.source not in seen:
            existing.append(b.to_dict())
            seen.add(b.source)
    json.dump(existing, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[save_triples] 共 {len(existing)} 批，已写入 {path}")


if __name__ == "__main__":
    # 自测：一段假数据，验证抽取逻辑通不通
    demo = """字节跳动2024年校招算法岗应届生年薪普遍35万，发15薪。
技术栈方面，后端主要用Go语言，机器学习训练平台基于PyTorch，推理服务大量使用Kubernetes。
梁汝波目前担任字节跳动CEO。公司业务涵盖抖音短视频、TikTok、今日头条等板块，属于短视频和人工智能行业。
面试流程通常为：在线笔试（1轮），技术一面，技术二面，交叉面，最后HR谈薪。"""
    b = extract_from_text("字节跳动_自测", demo)
    print("entities:", len(b.entities))
    for e in b.entities:
        print("  -", e)
    print("relations:", len(b.relations))
    for r in b.relations:
        print("  -", r)
    save_triples([b])
