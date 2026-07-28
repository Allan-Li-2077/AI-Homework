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
import uuid
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


# ── 会话存储（内存 dict，重启即清）───────────────────────────────────────────
sessions: dict[str, dict] = {}  # session_id → {"messages": [...], "mode": str}


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question:   str
    max_steps:  int = 10
    session_id: str | None = None


# ── SSE 流式生成器 ────────────────────────────────────────────────────────────
def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_react(question: str, max_steps: int, mode: str, session_id: str | None):
    """
    从会话中取出历史 messages，传给 ReAct 循环，
    循环结束后把更新后的 messages 存回会话。
    支持多轮对话：同一 session_id 的请求共享上下文。
    """
    if mode == "manual":
        from react_manual import run as react_run
        from react_manual import SYSTEM_PROMPT
    else:
        from react_function_calling import run as react_run
        from react_function_calling import FC_SYSTEM_PROMPT as SYSTEM_PROMPT

    # 获取或创建会话
    if session_id and session_id in sessions and sessions[session_id]["mode"] == mode:
        msgs = sessions[session_id]["messages"]
    else:
        if session_id and session_id in sessions:
            logger.warning("会话 %s 的模式从 %s 切换为 %s，创建新会话", session_id, sessions[session_id]["mode"], mode)
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        session_id = str(uuid.uuid4())
        sessions[session_id] = {"messages": msgs, "mode": mode}

    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _worker():
        try:
            for step_data in react_run(question, max_steps=max_steps, messages=msgs):
                queue.put_nowait(step_data)
        except Exception as exc:
            logger.exception("Agent 执行失败")
            queue.put_nowait({"type": "error", "observation": f"Agent 执行失败: {exc}"})
        finally:
            queue.put_nowait(_SENTINEL)

    yield _sse({"type": "start", "question": question, "mode": mode, "session_id": session_id})

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _worker)

    while True:
        step_data = await queue.get()
        if step_data is _SENTINEL:
            break
        yield _sse(step_data)

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


@app.post("/session/new")
async def new_session():
    """创建新会话，返回空 session_id"""
    sid = str(uuid.uuid4())
    return {"session_id": sid}


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话"""
    sessions.pop(session_id, None)
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "manual_model": os.getenv("MANUAL_AGENT_MODEL", "deepseek-chat"),
        "fc_model": os.getenv("FC_AGENT_MODEL", "deepseek-chat"),
    }


# ── 托管 index.html ──────────────────────────────────────────────────────────
HTML_PATH = Path(__file__).parent.parent / "index.html"

@app.get("/")
async def root():
    if HTML_PATH.exists():
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>index.html not found</h2>")
