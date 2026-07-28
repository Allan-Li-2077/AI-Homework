"""
FastAPI HTTP 服务，提供流式 SSE 接口给 Web UI

接口：
  POST /query/manual  - 手写版 ReAct，流式返回每步（支持多轮对话）
  POST /query/fc      - Function Calling 版，流式返回每步
  POST /session       - 创建新会话
  GET  /session/{id}  - 查看会话历史
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
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent))

from session_store import create_session, get_context, add_exchange, get_session, delete_session

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
    question:   str
    max_steps:  int = 10
    session_id: Optional[str] = None   # 可选，不传则自动创建新会话


# ── SSE 流式生成器 ────────────────────────────────────────────────────────────
def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_react(question: str, max_steps: int, mode: str,
                        session_id: str, context_rounds: list):
    """
    同步生成器（react_run）在独立线程中逐步执行，
    每产出一步通过 asyncio.Queue 传递给异步 SSE 生成器，
    实现真正的边思考边推送。
    
    流式结束后自动将问答对保存到会话存储。
    """
    if mode == "manual":
        from react_manual import run as react_run
    else:
        from react_function_calling import run as react_run

    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()
    final_answer: Optional[str] = None

    def _worker():
        nonlocal final_answer
        try:
            if mode == "manual":
                for step_data in react_run(question, max_steps=max_steps,
                                           context_rounds=context_rounds):
                    queue.put_nowait(step_data)
            else:
                for step_data in react_run(question, max_steps=max_steps):
                    queue.put_nowait(step_data)
        finally:
            queue.put_nowait(_SENTINEL)

    yield _sse({"type": "start", "question": question, "mode": mode,
                "session_id": session_id})

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _worker)

    while True:
        step_data = await queue.get()
        if step_data is _SENTINEL:
            break

        yield _sse(step_data)

        # 记录最终答案（用于会后存储）
        if step_data.get("type") in ("final", "max_steps"):
            final_answer = step_data.get("answer", "")

    # ── 流式结束后，保存问答到会话 ──────────────────────────────────────────
    if final_answer is not None:
        success = add_exchange(session_id, question, final_answer)
        if success:
            logger.info(f"会话 {session_id} 保存问答成功")
        else:
            logger.warning(f"会话 {session_id} 保存失败（会话可能已被删除）")

    yield _sse({"type": "done", "session_id": session_id})


# ── 路由 ──────────────────────────────────────────────────────────────────────
@app.post("/query/manual")
async def query_manual(req: QueryRequest):
    """手动 ReAct 模式，支持多轮对话"""
    sid = req.session_id or create_session()
    prev_rounds = get_context(sid)

    if prev_rounds:
        logger.info(f"会话 {sid} 加载了 {len(prev_rounds)} 轮历史上下文")

    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "manual", sid, prev_rounds),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/query/fc")
async def query_fc(req: QueryRequest):
    """Function Calling 模式（不加载上下文，每次独立）"""
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "fc", "", []),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/session")
async def new_session():
    """显式创建新会话"""
    sid = create_session()
    return {"session_id": sid, "message": "会话已创建"}


@app.get("/session/{session_id}")
async def view_session(session_id: str):
    """查看会话历史"""
    session = get_session(session_id)
    if session is None:
        return {"error": "会话不存在", "session_id": session_id}
    return session


@app.delete("/session/{session_id}")
async def remove_session(session_id: str):
    """删除会话"""
    ok = delete_session(session_id)
    if ok:
        return {"message": "会话已删除", "session_id": session_id}
    return {"error": "会话不存在", "session_id": session_id}


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
