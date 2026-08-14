"""
求职公司调研 - FastAPI HTTP + SSE 服务
严格仿照 market_research_subagents：queue 桥接跨线程、逐事件推送
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents import ResearchAgents, RunTrace
from src.build_graph import get_driver as neo4j_get_driver, STATS_JSON, make_uid, normalize_name


_agents_singleton: ResearchAgents | None = None
_neo4j_driver_singleton = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agents_singleton, _neo4j_driver_singleton
    _agents_singleton = ResearchAgents(serial=False)
    try:
        _neo4j_driver_singleton = neo4j_get_driver()
        print("[serve] Neo4j 连接成功")
    except Exception as e:
        print(f"[serve] Neo4j 不可用，降级为纯调研模式: {e}")
        _neo4j_driver_singleton = None
    yield
    if _neo4j_driver_singleton:
        _neo4j_driver_singleton.close()


app = FastAPI(title="Job Company Research Subagents", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = os.path.join(ROOT, "static", "index.html")
    if os.path.exists(html_path):
        return open(html_path, "r", encoding="utf-8").read()
    return HTMLResponse("""<h1>求职公司调研 - Subagent 并行 + 图谱沉淀</h1>
<p>API: <code>GET /run?question=...&company=...</code> 或 SSE <code>GET /stream</code>。</p>
<p>推荐先启动 Neo4j，然后调 research_or_query 接口体验「先查图后调研」。</p>""")


@app.get("/health")
def health():
    info = {"ok": True, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    if _neo4j_driver_singleton:
        try:
            with _neo4j_driver_singleton.session() as s:
                info["neo4j_nodes"] = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
                info["neo4j_edges"] = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        except Exception as e:
            info["neo4j_error"] = str(e)
    else:
        info["neo4j"] = "未连接"
    return info


@app.get("/graph/stats")
def graph_stats():
    """返回图谱当前规模、最近一次 build_graph 的统计"""
    if not _neo4j_driver_singleton:
        return {"error": "Neo4j 未连接"}
    with _neo4j_driver_singleton.session() as s:
        n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        r = s.run("MATCH ()-[rr]->() RETURN count(rr) AS c").single()["c"]
        labels = s.run("MATCH (n) RETURN DISTINCT labels(n)[0] AS lbl, count(n) AS c ORDER BY c DESC").data()
        rels = s.run("MATCH ()-[r]->() RETURN DISTINCT type(r) AS t, count(r) AS c ORDER BY c DESC").data()
    build_stats = None
    if os.path.exists(STATS_JSON):
        try:
            build_stats = json.load(open(STATS_JSON, "r", encoding="utf-8"))
        except Exception:
            pass
    return {"nodes": n, "edges": r, "by_label": labels, "by_relation": rels, "last_build": build_stats}


@app.get("/graph/subgraph")
def graph_subgraph(company: str, hop: int = 2):
    """
    前端 force_graph.js 配套接口：返回某公司 N 跳子图的 nodes/edges 数组。
    输出格式: {"nodes": [{uid,name,type}, ...], "edges": [{src,dst,rel}, ...]}
    """
    if not _neo4j_driver_singleton:
        return {"nodes": [], "edges": [], "error": "Neo4j 未连接"}
    std = normalize_name(company)
    uid = make_uid("Company", std)
    q = f"""
    MATCH path = (c:Company {{uid: $uid}})-[*1..{hop}]-(n)
    UNWIND nodes(path) AS nd
    WITH COLLECT(DISTINCT {{uid: nd.uid, name: nd.name, type: labels(nd)[0]}}) AS all_nodes
    MATCH path2 = (c2:Company {{uid: $uid}})-[rels*1..{hop}]-(n2)
    UNWIND rels AS rel
    WITH all_nodes,
         COLLECT(DISTINCT {{
             src: startNode(rel).uid,
             dst: endNode(rel).uid,
             rel: type(rel)
         }}) AS all_edges
    RETURN all_nodes, all_edges
    """
    try:
        with _neo4j_driver_singleton.session() as s:
            rec = s.run(q, uid=uid).single()
            nodes = rec["all_nodes"] or []
            edges = rec["all_edges"] or []
        # 公司节点本身如果上面的 MATCH 没走到（孤立节点），手动补一个
        if not any(n.get("uid") == uid for n in nodes):
            with _neo4j_driver_singleton.session() as s:
                lone = s.run("MATCH (c:Company {uid:$uid}) RETURN c.uid AS uid, c.name AS name, labels(c)[0] AS type", uid=uid).single()
                if lone:
                    nodes.append({"uid": lone["uid"], "name": lone["name"], "type": lone["type"]})
    except Exception as e:
        return {"nodes": [], "edges": [], "error": f"Cypher 失败: {type(e).__name__}: {e}"}
    return {"nodes": nodes, "edges": edges, "company": std, "hop": hop,
            "nodes_count": len(nodes), "edges_count": len(edges)}


@app.get("/run")
def run_sync(question: str = "", company: str = ""):
    """同步接口：直接返回 JSON。适合 CLI / Postman 简单测试"""
    if not _agents_singleton:
        return {"error": "agents 未初始化"}
    if company:
        trace: RunTrace = _agents_singleton.research_or_query(company, question or "业务、薪资、面试、技术栈、前景")
    else:
        trace: RunTrace = _agents_singleton.research(question)
    return trace.to_dict()


@app.get("/stream")
def stream(question: str = "", company: str = ""):
    """SSE 流式接口：逐事件推送 main_step / dispatch / subagent_step / graph_* / done。"""
    q: queue.Queue[dict | None] = queue.Queue()
    stopped = threading.Event()

    def evt_cb(evt_dict):
        q.put(evt_dict)

    def worker():
        try:
            agents = ResearchAgents(event_cb=evt_cb, serial=False)
            if company:
                trace = agents.research_or_query(company, question or "业务、薪资、面试、技术栈、前景")
            else:
                trace = agents.research(question)
            q.put({"kind": "final_trace", "data": trace.to_dict()})
        except Exception as e:
            import traceback
            q.put({"kind": "error", "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}"})
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        try:
            while True:
                item = q.get(timeout=120)
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        except queue.Empty:
            yield f"data: {json.dumps({'kind':'error','error':'SSE timeout'})}\n\n"
        finally:
            stopped.set()

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
