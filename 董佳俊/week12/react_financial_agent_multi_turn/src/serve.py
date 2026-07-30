"""
FastAPI HTTP 服务（多轮对话支持）

- 服务端 session 管理：session_id → 完整消息历史
- SSE 流式返回每步推理
- 30 分钟 TTL + 定期清理过期 session

接口：
  POST /query/manual     - 手写版 ReAct，流式返回每步
  POST /query/fc         - Function Calling 版，流式返回每步
  POST /session/create   - 创建新会话
  POST /session/delete   - 删除会话
  GET  /health           - 健康检查

使用方式：
  uvicorn serve:app --host 0.0.0.0 --port 8001
"""

import os
import sys
import uuid
import json
import logging
import asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Session 数据结构 ──────────────────────────────────────────────────────────

@dataclass
class Session:
    session_id: str
    messages: list = field(default_factory=list)
    mode: str = "manual"
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)


# ── 全局 Session 存储 ─────────────────────────────────────────────────────────

SESSIONS: dict[str, Session] = {}
SESSION_TTL = timedelta(minutes=30)
_LOCK = asyncio.Lock()


def _create_session(mode: str = "manual") -> Session:
    """创建新 session"""
    session_id = uuid.uuid4().hex[:12]
    session = Session(session_id=session_id, mode=mode)
    SESSIONS[session_id] = session
    logger.info(f"Session 创建: {session_id}")
    return session


def _get_session(session_id: str) -> Session | None:
    """获取 session，同时更新活跃时间"""
    session = SESSIONS.get(session_id)
    if session:
        session.last_active = datetime.now()
    return session


def _delete_session(session_id: str) -> bool:
    """删除 session"""
    existed = SESSIONS.pop(session_id, None) is not None
    if existed:
        logger.info(f"Session 删除: {session_id}")
    return existed


async def _cleanup_expired():
    """清理过期 session"""
    now = datetime.now()
    expired = [sid for sid, s in SESSIONS.items()
               if now - s.last_active > SESSION_TTL]
    for sid in expired:
        del SESSIONS[sid]
        logger.info(f"清理过期 session: {sid}")


async def _periodic_cleanup():
    """定期清理过期 session"""
    while True:
        await asyncio.sleep(300)  # 每 5 分钟清理一次
        await _cleanup_expired()


# ── 预加载 + 生命周期 ─────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("预加载 FAISS 索引...")
    from tools import _load_rag
    await asyncio.to_thread(_load_rag)
    logger.info("预加载完成，服务就绪")

    cleanup_task = asyncio.create_task(_periodic_cleanup())
    yield
    cleanup_task.cancel()


app = FastAPI(title="ReAct Financial Agent (Multi-Turn)", lifespan=lifespan)


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question:   str
    max_steps:  int  = 10
    session_id: str | None = None   # None 时自动创建新 session


class CreateSessionRequest(BaseModel):
    mode: str = "manual"


# ── SSE 流式生成器 ────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_react(question: str, max_steps: int, mode: str,
                         session_id: str | None = None):
    """
    同步生成器（react_run）在独立线程中逐步执行，
    每产出一步通过 asyncio.Queue 传递给异步 SSE 生成器，
    实现真正的边思考边推送。

    支持多轮对话：通过 session_id 获取历史消息，执行完成后更新 session。
    """
    if mode == "manual":
        from react_manual import run as react_run
    else:
        from react_function_calling import run as react_run

    # ── 获取或创建 session ──────────────────────────────────────────────
    async with _LOCK:
        session = _get_session(session_id) if session_id else None
        if session is None:
            session = _create_session(mode)
            prior_messages = None
        else:
            prior_messages = session.messages

    yield _sse({"type": "session_start", "session_id": session.session_id})

    # ── 执行 ReAct 循环 ─────────────────────────────────────────────────
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _worker():
        try:
            for step_data in react_run(question, max_steps=max_steps,
                                        messages=prior_messages):
                queue.put_nowait(step_data)
        finally:
            queue.put_nowait(_SENTINEL)

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _worker)

    while True:
        step_data = await queue.get()
        if step_data is _SENTINEL:
            break

        # session_messages 不转发给前端，仅更新 session
        if step_data.get("type") == "session_messages":
            async with _LOCK:
                session.messages = step_data["messages"]
            continue

        yield _sse(step_data)

    yield _sse({"type": "done"})


# ── Session 管理路由 ─────────────────────────────────────────────────────────

@app.post("/session/create")
async def create_session(req: CreateSessionRequest):
    session = _create_session(req.mode)
    return {"session_id": session.session_id, "mode": session.mode}


@app.post("/session/delete")
async def delete_session(req: dict):
    session_id = req.get("session_id", "")
    ok = _delete_session(session_id)
    return {"ok": ok, "session_id": session_id}


# ── Query 路由 ───────────────────────────────────────────────────────────────

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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": os.getenv("AGENT_MODEL", "qwen-max"),
        "active_sessions": sum(1 for s in SESSIONS.values()),
    }


# ── 托管 index.html ──────────────────────────────────────────────────────────

HTML_PATH = Path(__file__).parent.parent / "index.html"


@app.get("/")
async def root():
    if HTML_PATH.exists():
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>index.html not found</h2>")
