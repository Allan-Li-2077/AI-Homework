"""
求职公司调研 - 图谱检索模块（融合 GraphRAG Local Search 思路）
核心：先查 Neo4j 图谱里有没有这家公司，有就直接图检索（秒级），没有再走 subagent 并行调研。
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.build_graph import (
    get_driver, make_uid, normalize_name, COMPANY_ALIASES
)
from src import llm_client

LOCAL_SEARCH_SYSTEM = """你是一名求职咨询顾问，需要基于知识图谱子图中的信息，诚实回答用户关于某公司的问题。

要求：
1. 只使用【提供的子图信息】作答，严禁编造图谱中不存在的内容。
2. 如果子图中完全没有相关信息，明确回答"根据当前知识图谱未查询到相关信息"。
3. 结构清晰地列出要点，有具体数字尽量用具体数字。
4. 结尾给出一句免责声明：以上信息来源于历史调研结果，仅供参考，请以官方最新信息为准。
"""


def check_company_exists(driver, company_name: str) -> bool:
    """图谱中是否已经有这家公司节点（含别名匹配）"""
    std = normalize_name(company_name)
    uid = make_uid("Company", std)
    with driver.session() as sess:
        rec = sess.run("MATCH (c:Company {uid:$uid}) RETURN count(c) AS c", uid=uid).single()
        return rec["c"] > 0


def fetch_local_subgraph(driver, company_name: str, hop: int = 2) -> list[dict]:
    """
    从某公司节点出发，拉 1~2 跳邻居子图，返回三元组列表（给 LLM 合成用）。
    每条: {"s": (name, type), "rel": str, "t": (name, type), "attrs": dict}
    不用 APOC 插件，纯原生 Cypher：
      - 1 跳直接关系：(c)-[r1]-(n1)
      - 2 跳扩展关系：(n1)-[r2]-(n2)
    """
    std = normalize_name(company_name)
    uid = make_uid("Company", std)

    # 1 跳边 (c)-[r]-(n)
    q1_hop = """
    MATCH (c:Company {uid: $uid})-[r]-(n)
    RETURN
      startNode(r).name AS s_name, labels(startNode(r))[0] AS s_type,
      type(r) AS rel, properties(r) AS rel_attrs,
      endNode(r).name AS t_name, labels(endNode(r))[0] AS t_type
    """

    # 2 跳扩展 (n1)-[r2]-(n2)，其中 n1 是 c 的 1 跳邻居
    q2_hop = """
    MATCH (c:Company {uid: $uid})--(n1)-[r2]-(n2)
    WHERE n2.uid <> $uid
    RETURN
      startNode(r2).name AS s_name, labels(startNode(r2))[0] AS s_type,
      type(r2) AS rel, properties(r2) AS rel_attrs,
      endNode(r2).name AS t_name, labels(endNode(r2))[0] AS t_type
    """

    triples = []
    seen = set()
    with driver.session() as sess:
        for rec in sess.run(q1_hop, uid=uid):
            key = (rec["s_name"], rec["s_type"], rec["rel"], rec["t_name"], rec["t_type"])
            if key in seen:
                continue
            seen.add(key)
            triples.append({
                "s": (rec["s_name"], rec["s_type"]),
                "rel": rec["rel"],
                "t": (rec["t_name"], rec["t_type"]),
                "attrs": rec["rel_attrs"] or {},
            })
        if hop >= 2:
            for rec in sess.run(q2_hop, uid=uid):
                key = (rec["s_name"], rec["s_type"], rec["rel"], rec["t_name"], rec["t_type"])
                if key in seen:
                    continue
                seen.add(key)
                triples.append({
                    "s": (rec["s_name"], rec["s_type"]),
                    "rel": rec["rel"],
                    "t": (rec["t_name"], rec["t_type"]),
                    "attrs": rec["rel_attrs"] or {},
                })
    return triples


def format_subgraph_for_llm(triples: list[dict]) -> str:
    if not triples:
        return "（子图为空）"
    lines = ["【知识图谱子图 - 三元组列表】"]
    for t in triples:
        s_name, s_type = t["s"]
        t_name, t_type = t["t"]
        attr = ""
        if t["attrs"]:
            attr = "  " + json.dumps(t["attrs"], ensure_ascii=False)
        lines.append(f"- ({s_type}:{s_name}) -[{t['rel']}]-> ({t_type}:{t_name}){attr}")
    return "\n".join(lines)


def search_via_graph(driver, company_name: str, question: str) -> dict:
    """
    Local Search：子图 → LLM 合成 → 答案。
    返回 dict: {"answer": str, "subgraph_triples": int, "elapsed_ms": int, "from_graph": True}
    """
    t0 = time.perf_counter()
    triples = fetch_local_subgraph(driver, company_name, hop=2)
    subgraph_text = format_subgraph_for_llm(triples)

    user_msg = f"""【公司名】{company_name}
【用户问题】{question}
{subgraph_text}

请基于子图信息，诚实回答用户问题。"""

    answer = llm_client.chat([
        {"role": "system", "content": LOCAL_SEARCH_SYSTEM},
        {"role": "user", "content": user_msg},
    ], temperature=0.2, max_tokens=2048)

    return {
        "answer": answer.strip(),
        "subgraph_triples": len(triples),
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "from_graph": True,
    }


if __name__ == "__main__":
    # 自测：看一下图谱里有没有某家公司的信息
    driver = get_driver()
    comp = "字节跳动"
    print(f"[{comp}] 在库中？", check_company_exists(driver, comp))
    if check_company_exists(driver, comp):
        t = fetch_local_subgraph(driver, comp, hop=2)
        print(format_subgraph_for_llm(t))
        res = search_via_graph(driver, comp, "字节跳动的技术栈是什么？")
        print("Answer:", res["answer"])
    driver.close()
