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
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
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


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question:  str
    max_steps: int = 10
    conversation_id: str | None = None


MAX_HISTORY_TURNS = int(os.getenv("AGENT_MAX_HISTORY_TURNS", "8"))
_conversation_histories: dict[str, list[dict[str, str]]] = {}
_conversation_lock = threading.RLock()


def _new_conversation_id() -> str:
    return uuid.uuid4().hex


def _normalize_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    allowed_roles = {"user", "assistant"}
    normalized = []
    for msg in history:
        role = msg.get("role")
        content = msg.get("content")
        if role in allowed_roles and isinstance(content, str) and content.strip():
            normalized.append({"role": role, "content": content})
    return normalized[-MAX_HISTORY_TURNS * 2 :]


def _get_history(conversation_id: str) -> list[dict[str, str]]:
    with _conversation_lock:
        return list(_conversation_histories.get(conversation_id, []))


def _append_turn(conversation_id: str, question: str, answer: str) -> None:
    with _conversation_lock:
        history = _conversation_histories.setdefault(conversation_id, [])
        history.extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ])
        _conversation_histories[conversation_id] = _normalize_history(history)


# ── SSE 流式生成器 ────────────────────────────────────────────────────────────
def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_react(
    question: str,
    max_steps: int,
    mode: Literal["manual", "fc"],
    conversation_id: str | None = None,
):
    """
    同步生成器（react_run）在独立线程中逐步执行，
    每产出一步通过 asyncio.Queue 传递给异步 SSE 生成器，
    实现真正的边思考边推送。
    """
    if mode == "manual":
        from react_manual import run as react_run
    else:
        from react_function_calling import run as react_run

    conversation_id = conversation_id or _new_conversation_id()
    history = _get_history(conversation_id)

    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()
    final_answer = None

    loop = asyncio.get_event_loop()

    def _worker():
        nonlocal final_answer
        try:
            for step_data in react_run(question, max_steps=max_steps, history=history):
                if step_data.get("type") in {"final", "max_steps"}:
                    final_answer = step_data.get("answer")
                loop.call_soon_threadsafe(queue.put_nowait, step_data)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    yield _sse({
        "type": "start",
        "question": question,
        "mode": mode,
        "conversation_id": conversation_id,
        "history_turns": len(history) // 2,
    })

    loop.run_in_executor(None, _worker)

    while True:
        step_data = await queue.get()
        if step_data is _SENTINEL:
            break
        yield _sse(step_data)

    if final_answer:
        _append_turn(conversation_id, question, final_answer)

    yield _sse({"type": "done", "conversation_id": conversation_id})


# ── 路由 ──────────────────────────────────────────────────────────────────────
@app.post("/query/manual")
async def query_manual(req: QueryRequest):
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "manual", req.conversation_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/query/fc")
async def query_fc(req: QueryRequest):
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "fc", req.conversation_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "provider": os.getenv("LLM_PROVIDER", "dashscope"),
        "model": os.getenv("AGENT_MODEL", "qwen-max"),
    }


# ── 托管 index.html ──────────────────────────────────────────────────────────
HTML_PATH = Path(__file__).parent.parent / "index.html"

@app.get("/")
async def root():
    if HTML_PATH.exists():
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>index.html not found</h2>")
