"""
图编排 Supervisor HTTP 服务（FastAPI + SSE 流式）

教学重点：
  SSE 逐事件推送，前端实时看到：
  - plan 事件：确定性路由完成，整张 DAG 预画（含依赖边）
  - node_start / node_step：各 worker 开始 + 每步 Thought/Action/Observation
  - node_done / stats / final：节点完成、并行加速统计、最终交付

启动：
  uvicorn src.serve:app --host 0.0.0.0 --port 8003
  浏览器开 http://localhost:8003
（旧项目 market_research_subagents 用 8002，互不冲突）

依赖：pip install fastapi uvicorn
"""
import json
import logging
import os
import queue
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    logger.info("图编排 Supervisor 服务就绪（确定性路由 + 异构 worker 并行）")
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class QueryRequest(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "ok",
            "llm": bool(os.getenv("DEEPSEEK_API_KEY")),
            "tavily": bool(os.getenv("TAVILY_API_KEY"))}


@app.post("/query")
def query(req: QueryRequest):
    """SSE 流式：start → plan → node_* → stats → final → done。"""
    import graph as graph_mod

    def event_stream():
        q = queue.Queue()
        SENTINEL = object()

        def run():
            try:
                graph_mod.run_graph(req.question, on_event=q.put, save_trace=True)
            except Exception as e:
                q.put({"type": "error", "message": f"{type(e).__name__}: {str(e)[:200]}"})
            finally:
                q.put(SENTINEL)

        # 旧坑 #6：调研在 worker 线程跑，SSE 在主线程——queue 桥接
        threading.Thread(target=run, daemon=True).start()

        while True:
            ev = q.get()
            if ev is SENTINEL:
                break                       # run_graph 已发过 done 事件，这里只负责结束流
            yield "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("serve:app", host="0.0.0.0", port=8003, reload=False)
