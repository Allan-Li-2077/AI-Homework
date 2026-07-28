"""
FastAPI HTTP 服务，提供流式 SSE 接口给 Web UI

接口：
  POST /query/manual     - 手写版 ReAct，流式返回每步
  POST /query/fc         - Function Calling 版，流式返回每步（支持 session）
  GET  /health           - 健康检查
  POST /session/new      - 创建新会话
  POST /session/{id}/reset - 重置会话历史
  GET  /session/{id}/history - 查看会话 Q&A 历史

使用方式：
  uvicorn serve:app --host 0.0.0.0 --port 8000
"""

import os
import sys
import json
import uuid
import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent))

from react_function_calling import ReActSession  # noqa: E402

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

# ── 会话存储（生产环境可替换为 Redis）─────────────────────────────────────────
_sessions: dict[str, ReActSession] = {}


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question:   str
    max_steps:  int = 10
    session_id: str | None = None  # 可选：传入 session_id 以保持跨问答记忆


# ── SSE 流式生成器 ────────────────────────────────────────────────────────────
def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_react(
    question: str,
    max_steps: int,
    mode: str,
    session: ReActSession | None = None,
    session_id: str | None = None,
):
    """
    同步生成器在独立线程中逐步执行，每产出一步通过 asyncio.Queue
    传递给异步 SSE 生成器，实现真正的边思考边推送。

    若传入 session，则在已有对话历史上继续推理（跨问答记忆）；
    否则创建临时 session（每次独立）。
    """
    if session is not None:
        # 使用传入的持久化 session
        def _gen():
            yield from session.run(question, max_steps=max_steps)
    elif mode == "manual":
        from react_manual import run as _run_manual
        def _gen():
            yield from _run_manual(question, max_steps=max_steps)
    else:
        from react_function_calling import run as _run_fc
        def _gen():
            yield from _run_fc(question, max_steps=max_steps)

    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _worker():
        try:
            for step_data in _gen():
                queue.put_nowait(step_data)
        finally:
            queue.put_nowait(_SENTINEL)

    yield _sse({
        "type": "start",
        "question": question,
        "mode": mode,
        "session_id": session_id,
    })

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _worker)

    while True:
        step_data = await queue.get()
        if step_data is _SENTINEL:
            break
        yield _sse(step_data)

    yield _sse({"type": "done"})


# ── 会话辅助 ──────────────────────────────────────────────────────────────────
def _get_or_create_session(session_id: str | None) -> tuple[ReActSession, str | None]:
    """获取或创建 session，返回 (session, session_id)。"""
    if session_id and session_id in _sessions:
        return _sessions[session_id], session_id
    new_session = ReActSession()
    if session_id:
        _sessions[session_id] = new_session
    return new_session, session_id


# ── 路由 ──────────────────────────────────────────────────────────────────────
@app.post("/query/manual")
async def query_manual(req: QueryRequest):
    session, sid = _get_or_create_session(req.session_id)
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "manual",
                      session=session, session_id=sid),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/query/fc")
async def query_fc(req: QueryRequest):
    session, sid = _get_or_create_session(req.session_id)
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "fc",
                      session=session, session_id=sid),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model": os.getenv("AGENT_MODEL", "qwen-max")}


# ── 会话管理端点 ──────────────────────────────────────────────────────────────
@app.post("/session/new")
async def create_session():
    """创建新会话，返回 session_id。"""
    session_id = str(uuid.uuid4())[:8]
    _sessions[session_id] = ReActSession()
    logger.info("新会话创建: %s", session_id)
    return {"session_id": session_id, "status": "created"}


@app.post("/session/{session_id}/reset")
async def reset_session(session_id: str):
    """重置会话的对话历史（保留 system prompt）。"""
    session = _sessions.get(session_id)
    if session is None:
        return {"error": "Session not found", "session_id": session_id}
    session.reset()
    logger.info("会话已重置: %s", session_id)
    return {"session_id": session_id, "status": "reset"}


@app.get("/session/{session_id}/history")
async def get_session_history(session_id: str):
    """查看会话的 Q&A 历史。"""
    session = _sessions.get(session_id)
    if session is None:
        return {"error": "Session not found", "session_id": session_id}
    return {
        "session_id": session_id,
        "history": session.history,
        "message_count": session.message_count,
    }


# ── 托管 index.html ──────────────────────────────────────────────────────────
HTML_PATH = Path(__file__).parent.parent / "index.html"

@app.get("/")
async def root():
    if HTML_PATH.exists():
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>index.html not found</h2>")
