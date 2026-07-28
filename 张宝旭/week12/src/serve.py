"""FastAPI HTTP 服务，提供流式 SSE 接口给 Web UI。

接口：
  POST /query/manual  - 手写版 ReAct，流式返回每步
  POST /query/fc      - Function Calling 版，流式返回每步
  GET  /health        - 健康检查
  GET  /sessions      - 会话列表
  POST /sessions      - 创建新会话
  GET  /sessions/{id}  - 获取会话详情
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSION_FILE = PROJECT_ROOT / "sessions.jsonl"


# ── 预加载 FAISS（启动时执行一次）────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("预加载 FAISS 索引和 Embedding 模型...")
    from session_store import JsonlSessionStore
    from tools import _load_rag

    app.state.session_store = JsonlSessionStore(SESSION_FILE)
    await asyncio.to_thread(_load_rag)
    logger.info("预加载完成，服务就绪")
    yield


app = FastAPI(title="ReAct Financial Agent", lifespan=lifespan)


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question: str
    max_steps: int = 10
    session_id: str | None = None


class CreateSessionRequest(BaseModel):
    title: str | None = None
    mode: str = "manual"


# ── SSE 流式生成器 ────────────────────────────────────────────────────────────
def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _session_store():
    return app.state.session_store


def _mode_to_runner(mode: str):
    if mode == "manual":
        from react_manual import run as react_run
    else:
        from react_function_calling import run as react_run
    return react_run


async def _stream_react(
    question: str,
    max_steps: int,
    mode: str,
    session_id: str | None,
):
    """逐步执行 ReAct，并在结束后把会话写回 JSONL。"""
    store = _session_store()
    session = store.ensure(session_id, title=question, mode=mode)
    messages = session.messages
    react_run = _mode_to_runner(mode)
    final_text = ""

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _worker():
        try:
            for step_data in react_run(
                question,
                max_steps=max_steps,
                messages=messages,
            ):
                loop.call_soon_threadsafe(queue.put_nowait, step_data)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    yield _sse(
        {
            "type": "start",
            "question": question,
            "mode": mode,
            "session_id": session.session_id,
            "session_title": session.title,
        }
    )

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _worker)

    while True:
        step_data = await queue.get()
        if step_data is _SENTINEL:
            break

        if step_data.get("type") in {"final", "max_steps", "error"}:
            final_text = (
                step_data.get("answer")
                or step_data.get("observation")
                or ""
            )

        yield _sse(step_data)

    if final_text:
        store.append_turn(
            session.session_id,
            question,
            final_text,
            mode,
            messages,
        )
    else:
        store.update_messages(session.session_id, messages, mode=mode)

    yield _sse({"type": "done", "session_id": session.session_id})


# ── 路由 ──────────────────────────────────────────────────────────────────────
@app.get("/sessions")
async def list_sessions():
    return _session_store().list_sessions()


@app.post("/sessions")
async def create_session(req: CreateSessionRequest):
    session = _session_store().create(title=req.title, mode=req.mode)
    return session.to_dict()


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = _session_store().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session.to_dict()


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
    from provider import get_provider_config

    chat_cfg = get_provider_config("chat")
    embed_cfg = get_provider_config("embed")
    return {
        "status": "ok",
        "chat_model": chat_cfg.chat_model,
        "chat_provider": chat_cfg.provider,
        "embed_model": embed_cfg.embed_model,
        "embed_provider": embed_cfg.provider,
    }


# ── 托管 index.html ──────────────────────────────────────────────────────────
HTML_PATH = Path(__file__).parent.parent / "index.html"


@app.get("/")
async def root():
    if HTML_PATH.exists():
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>index.html not found</h2>")
