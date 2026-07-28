"""
带工具调用的多轮对话 Web 服务。
"""

import os
import sys
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from react_manual import ConversationSession  # noqa: E402
from tools import _load_rag  # noqa: E402

SESSIONS: dict[str, ConversationSession] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("预加载 FAISS 索引...")
    await asyncio.to_thread(_load_rag)
    logger.info("预加载完成")
    yield


app = FastAPI(title="ReAct Financial Agent", lifespan=lifespan)


class QueryRequest(BaseModel):
    question: str
    max_steps: int = 10
    session_id: Optional[str] = None
    reset: bool = False


class ResetRequest(BaseModel):
    session_id: Optional[str] = None


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_session(session_id: Optional[str], reset: bool = False) -> tuple[str, ConversationSession]:
    if not session_id:
        session_id = uuid4().hex
    if reset or session_id not in SESSIONS:
        SESSIONS[session_id] = ConversationSession()
    return session_id, SESSIONS[session_id]


async def _stream_turn(question: str, max_steps: int, session_id: str, session: ConversationSession):
    yield _sse({"type": "start", "question": question, "session_id": session_id})

    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()
    loop = asyncio.get_running_loop()

    def _worker():
        try:
            for step_data in session.ask(question, max_steps=max_steps):
                loop.call_soon_threadsafe(queue.put_nowait, step_data)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    loop.run_in_executor(None, _worker)

    while True:
        step_data = await queue.get()
        if step_data is sentinel:
            break
        yield _sse(step_data)

    yield _sse({"type": "done", "session_id": session_id})


@app.post("/query")
async def query(req: QueryRequest):
    session_id, session = _get_session(req.session_id, reset=req.reset)
    return StreamingResponse(
        _stream_turn(req.question, req.max_steps, session_id, session),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/reset")
async def reset(req: ResetRequest):
    session_id, _ = _get_session(req.session_id, reset=True)
    return {"status": "ok", "session_id": session_id}


@app.get("/health")
async def health():
    return {"status": "ok", "model": os.getenv("AGENT_MODEL", "mimo-v2.5-pro"), "sessions": len(SESSIONS)}


HTML_PATH = Path(__file__).parent.parent / "index.html"


@app.get("/")
async def root():
    if HTML_PATH.exists():
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>index.html not found</h2>")
