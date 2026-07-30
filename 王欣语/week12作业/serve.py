"""
FastAPI HTTP 服务，提供流式 SSE 接口给 Web UI

接口：
  POST /query/manual  - 手写版 ReAct，流式返回每步
  POST /query/fc      - Function Calling 版，流式返回每步
  GET  /health        - 健康检查

使用方式：
  uvicorn serve:app --host 0.0.0.0 --port 8000
"""

import os
import sys
import json
import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── 预加载 FAISS（启动时执行一次）────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("预加载 FAISS 索引和 Embedding 模型...")
    from tools import _load_rag
    await asyncio.to_thread(_load_rag)
    logger.info("预加载完成，服务就绪")
    yield


app = FastAPI(title="ReAct Financial Agent", lifespan=lifespan)


# ── 会话管理（内存存储）───────────────────────────────────────────────────────
# key: session_id, value: 该会话的完整 messages 列表（不含 system prompt）
sessions: dict[str, list] = {}


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question:   str
    max_steps:  int = 10
    session_id: str = "default"


# ── SSE 流式生成器 ────────────────────────────────────────────────────────────
def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_react(question: str, max_steps: int, mode: str, session_id: str = "default"):
    """
    同步生成器（react_run）在独立线程中逐步执行，
    每产出一步通过 asyncio.Queue 传递给异步 SSE 生成器，
    实现真正的边思考边推送。
    
    多轮对话支持：根据 session_id 读取/保存对话历史。
    """
    if mode == "manual":
        from react_manual import run as react_run
    else:
        from react_function_calling import run as react_run

    # 读取该 session 的历史
    history = sessions.get(session_id, [])

    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _worker():
        try:
            for step_data in react_run(question, max_steps=max_steps, history=history):
                queue.put_nowait(step_data)
        finally:
            queue.put_nowait(_SENTINEL)

    yield _sse({"type": "start", "question": question, "mode": mode, "session_id": session_id})

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _worker)

    # 收集最后一步的 messages 用于保存会话历史
    final_messages = None

    while True:
        step_data = await queue.get()
        if step_data is _SENTINEL:
            break
        # 保存最终 messages
        if "messages" in step_data:
            final_messages = step_data["messages"]
        yield _sse(step_data)

    # 保存更新后的会话历史
    if final_messages is not None:
        sessions[session_id] = final_messages
        logger.info(f"Session '{session_id}' 历史已更新，共 {len(final_messages)} 条消息")

    yield _sse({"type": "done"})


# ── 路由 ──────────────────────────────────────────────────────────────────────
@app.post("/query/manual")
async def query_manual(req: QueryRequest):
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "manual", req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/query/fc")
async def query_fc(req: QueryRequest):
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "fc", req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/session/clear")
async def clear_session(session_id: str = "default"):
    """清空指定会话的历史记录"""
    if session_id in sessions:
        del sessions[session_id]
        logger.info(f"Session '{session_id}' 已清空")
        return {"status": "ok", "message": f"会话 '{session_id}' 已清空"}
    return {"status": "ok", "message": f"会话 '{session_id}' 不存在或已为空"}


@app.get("/session/history")
async def get_session_history(session_id: str = "default"):
    """查看指定会话的历史记录（调试用）"""
    history = sessions.get(session_id, [])
    return {
        "session_id": session_id,
        "message_count": len(history),
        "history": history,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "model": os.getenv("AGENT_MODEL", "qwen-max")}


# ── 托管 index.html ──────────────────────────────────────────────────────────
HTML_PATH = Path(__file__).parent.parent / "index.html"

@app.get("/")
async def root():
    if HTML_PATH.exists():
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>index.html not found</h2>")
