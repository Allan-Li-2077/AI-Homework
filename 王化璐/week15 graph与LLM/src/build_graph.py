"""
求职公司调研 - 三元组 -> Neo4j 图谱构建
参考 graphrag_financial_report 项目，别名表改成求职公司
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from neo4j import GraphDatabase

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.extract_triples import TRIPLES_JSON

# ============================================================
# Neo4j 连接参数——默认本地 bolt + 关认证
# ============================================================
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "")
NEO4J_AUTH = (NEO4J_USER, NEO4J_PASS) if NEO4J_USER else None

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATS_JSON = os.path.join(DATA_DIR, "graph_stats.json")

# ============================================================
# 别名表：LLM 抽取的公司名五花八门，统一成标准名
# 你调研过的公司持续往这里加就行
# ============================================================
COMPANY_ALIASES = {
    "字节跳动": ["字节跳动", "字节", "抖音集团", "ByteDance", "bytedance", "北京抖音信息服务有限公司"],
    "百度":     ["百度", "Baidu", "百度公司", "小度科技"],
    "腾讯":     ["腾讯", "Tencent", "腾讯控股", "鹅厂", "深圳市腾讯计算机系统有限公司"],
    "阿里巴巴": ["阿里巴巴", "阿里", "Alibaba", "阿里集团", "淘宝中国"],
    "美团":     ["美团", "Meituan", "美团点评"],
    "商汤科技": ["商汤科技", "商汤", "SenseTime", "北京市商汤科技开发有限公司"],
    "旷视科技": ["旷视科技", "旷视", "Megvii", "北京旷视科技有限公司"],
    "科大讯飞": ["科大讯飞", "讯飞", "iFLYTEK", "安徽科大讯飞信息科技股份有限公司"],
    "云从科技": ["云从科技", "云从", "CloudWalk"],
    "宁德时代": ["宁德时代", "CATL", "宁德时代新能源"],
    "华为":     ["华为", "Huawei", "华为技术有限公司", "华为终端", "2012实验室"],
    "小米":     ["小米", "Xiaomi", "小米科技", "北京小米科技有限责任公司"],
    "快手":     ["快手", "Kuaishou", "北京快手科技有限公司"],
    "滴滴":     ["滴滴", "DiDi", "滴滴出行"],
    "拼多多":   ["拼多多", "Pinduoduo", "PDD"],
    "京东":     ["京东", "JD", "京东集团"],
    "网易":     ["网易", "NetEase", "网易公司"],
    "蚂蚁集团": ["蚂蚁集团", "蚂蚁", "Ant Group", "蚂蚁科技集团"],
}


def build_alias_to_standard() -> dict:
    """把别名表展开成 {别名: 标准名} 映射，大小写不敏感匹配"""
    m = {}
    for std, aliases in COMPANY_ALIASES.items():
        for a in aliases:
            m[a.lower()] = std
        m[std.lower()] = std
    return m


ALIAS_MAP = build_alias_to_standard()

# 节点 uid 生成：保持跟 GraphRAG 项目一致
_PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


def normalize_name(name: str) -> str:
    """归一化实体名 + 公司别名统一"""
    n = (name or "").strip()
    lower = n.lower()
    if lower in ALIAS_MAP:
        return ALIAS_MAP[lower]
    return n


def make_uid(ntype: str, name: str) -> str:
    key = f"{ntype}||{normalize_name(name)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


MERGE_NODE_CYPHER = """
MERGE (n {uid: $uid})
SET n:%s, n.name = $name
RETURN n.uid
"""

MERGE_REL_CYPHER = """
MATCH (s {uid: $s_uid})
MATCH (t {uid: $t_uid})
MERGE (s)-[r:%s]->(t)
SET r += $attrs
RETURN type(r)
"""


def get_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    driver.verify_connectivity()
    return driver


def ensure_constraints(driver):
    """给每种实体类型建唯一约束（uid 唯一）。Neo4j Community 版每个标签一个约束。"""
    labels = ["Company", "BusinessSegment", "SalaryIndicator",
              "TechnologyStack", "Person", "Industry", "InterviewProcess"]
    with driver.session() as sess:
        for lbl in labels:
            try:
                sess.run(f"""
                    CREATE CONSTRAINT {lbl}_uid_unique IF NOT EXISTS
                    FOR (n:{lbl}) REQUIRE n.uid IS UNIQUE
                """)
            except Exception as e:
                print(f"[约束] {lbl} 跳过: {e}")


def load_triples(path: str = TRIPLES_JSON):
    if not os.path.exists(path):
        print(f"[load_triples] 文件不存在：{path}，先运行 extract_triples 或 agents.py 调研后存图")
        return [], []
    data = json.load(open(path, "r", encoding="utf-8"))
    entities, relations = [], []
    for batch in data:
        for e in batch.get("entities", []):
            e["name"] = normalize_name(e["name"])
            entities.append(e)
        for r in batch.get("relations", []):
            r["subject"] = normalize_name(r["subject"])
            r["object"] = normalize_name(r["object"])
            relations.append(r)
    return entities, relations


def build_in_neo4j(driver, entities: list[dict], relations: list[dict]) -> dict:
    """把 (entities, relations) 批处理进 Neo4j。返回统计数据。"""
    t0 = time.perf_counter()
    node_count, edge_count = 0, 0
    seen_nodes, seen_edges = set(), set()

    with driver.session() as sess:
        # 1) 节点：先去重（按 uid），再 MERGE
        for e in entities:
            try:
                name = e["name"]
                ntype = e["type"]
            except KeyError:
                continue
            uid = make_uid(ntype, name)
            if uid in seen_nodes:
                continue
            seen_nodes.add(uid)
            try:
                sess.run(MERGE_NODE_CYPHER % ntype, uid=uid, name=name)
                node_count += 1
            except Exception as ex:
                print(f"[节点失败] {ntype}/{name}: {ex}")

        # 2) 边：按 (s_uid, rel, t_uid) 去重
        for r in relations:
            try:
                s, st = r["subject"], r["subject_type"]
                t, tt = r["object"], r["object_type"]
                rel = r["relation"]
            except KeyError:
                continue
            s_uid = make_uid(st, s)
            t_uid = make_uid(tt, t)
            key = (s_uid, rel, t_uid)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            attrs = dict(r.get("attributes") or {})
            # attrs 里 list/dict 转字符串（Neo4j 属性不支持嵌套结构）
            for k, v in list(attrs.items()):
                if isinstance(v, (list, dict)):
                    attrs[k] = json.dumps(v, ensure_ascii=False)
            try:
                sess.run(MERGE_REL_CYPHER % rel, s_uid=s_uid, t_uid=t_uid, attrs=attrs)
                edge_count += 1
            except Exception as ex:
                print(f"[边失败] {s}-[{rel}]->{t}: {ex}")

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # 3) 读全库规模，做个统计
    with driver.session() as sess:
        n_total = sess.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        r_total = sess.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

    stats = {
        "merged_nodes": node_count,
        "merged_edges": edge_count,
        "total_nodes": n_total,
        "total_edges": r_total,
        "elapsed_ms": elapsed_ms,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    json.dump(stats, open(STATS_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return stats


def main(triples_path: str = TRIPLES_JSON):
    print(f"[build_graph] 连接 Neo4j: {NEO4J_URI} (auth={'开启' if NEO4J_AUTH else '关闭'})")
    driver = get_driver()
    ensure_constraints(driver)
    entities, relations = load_triples(triples_path)
    print(f"[build_graph] 待合并：实体候选 {len(entities)}，关系候选 {len(relations)}")
    stats = build_in_neo4j(driver, entities, relations)
    print(f"[build_graph] 完成：{json.dumps(stats, ensure_ascii=False, indent=2)}")
    driver.close()


if __name__ == "__main__":
    main()
