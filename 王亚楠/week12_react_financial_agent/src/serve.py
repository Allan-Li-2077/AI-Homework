"""
FastAPI HTTP 服务，提供流式 SSE 接口给 Web UI

接口：
  POST /query/manual     - 手写版 ReAct，单次查询
  POST /query/fc         - Function Calling 版，单次查询
  POST /chat/manual      - 手写版 ReAct，多轮对话（同 session 共享上下文）
  POST /chat/fc          - Function Calling 版，多轮对话
  DELETE /chat/session/{id} - 重置对话上下文
  GET  /health           - 健康检查
  GET  /memory/stats     - 记忆统计
  ...

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

from fastapi import FastAPI, Request
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
    from tools import _load_rag, set_memory_store
    await asyncio.to_thread(_load_rag)

    # 初始化记忆系统并注入到 tools 模块
    from memory import MemoryStore
    app.state.memory = MemoryStore()
    set_memory_store(app.state.memory)
    stats = app.state.memory.get_stats()
    logger.info(f"记忆系统就绪: {stats['facts_count']} 条事实, "
                f"{stats['sessions_count']} 个会话")

    # 初始化 Chat 会话管理（多轮对话状态）
    app.state.chat_sessions: dict[str, object] = {}

    logger.info("预加载完成，服务就绪")
    yield


app = FastAPI(title="ReAct Financial Agent", lifespan=lifespan)


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
    """
    if mode == "manual":
        from react_manual import run as react_run
    else:
        from react_function_calling import run as react_run

    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    # 获取注入的记忆存储
    from tools import get_memory_store
    memory = get_memory_store()

    def _worker():
        try:
            for step_data in react_run(question, max_steps=max_steps,
                                       memory=memory, session_id=session_id):
                queue.put_nowait(step_data)
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


# ── 多轮对话（Chat）SSE 流式生成器 ────────────────────────────────────────────

async def _stream_chat(question: str, max_steps: int, mode: str, session_id: str):
    """
    使用 ChatSession 进行多轮对话——同一 session_id 的请求共享上下文。
    """
    from chat import ChatSession

    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _worker():
        try:
            # 获取或创建 ChatSession
            key = f"{mode}:{session_id}"
            app.state.chat_sessions.setdefault(key, {})
            if key not in app.state.chat_sessions or app.state.chat_sessions[key] is None:
                from tools import get_memory_store
                memory = get_memory_store()
                app.state.chat_sessions[key] = ChatSession(
                    mode=mode, memory=memory, session_id=session_id
                )
            chat = app.state.chat_sessions[key]

            for step_data in chat.send(question, max_steps=max_steps):
                queue.put_nowait(step_data)
        except Exception as e:
            queue.put_nowait({"type": "error", "observation": str(e)})
        finally:
            queue.put_nowait(_SENTINEL)

    yield _sse({"type": "start", "question": question, "mode": mode,
                "session_id": session_id, "chat": True})

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _worker)

    while True:
        step_data = await queue.get()
        if step_data is _SENTINEL:
            break
        yield _sse(step_data)

    yield _sse({"type": "done"})


# ── 路由 ──────────────────────────────────────────────────────────────────────

@app.post("/chat/manual")
async def chat_manual(req: QueryRequest):
    """多轮对话 — 手写版（同一 session_id 请求共享上下文）"""
    return StreamingResponse(
        _stream_chat(req.question, req.max_steps, "manual", req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat/fc")
async def chat_fc(req: QueryRequest):
    """多轮对话 — Function Calling 版"""
    return StreamingResponse(
        _stream_chat(req.question, req.max_steps, "fc", req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/chat/session/{session_id}")
async def chat_clear(session_id: str, request: Request):
    """重置指定会话的对话上下文（记忆不受影响）"""
    keys_to_clear = [k for k in request.app.state.chat_sessions if k.endswith(f":{session_id}")]
    for k in keys_to_clear:
        request.app.state.chat_sessions[k] = None
    return {"status": "ok", "cleared": len(keys_to_clear)}


@app.get("/health")
async def health():
    return {"status": "ok", "model": os.getenv("AGENT_MODEL", "qwen-max")}


# ── 记忆管理 API ──────────────────────────────────────────────────────────────
@app.get("/memory/stats")
async def memory_stats(request: Request):
    """获取记忆系统统计信息"""
    memory = request.app.state.memory
    return memory.get_stats()


@app.get("/memory/sessions")
async def memory_sessions(request: Request):
    """列出所有会话"""
    memory = request.app.state.memory
    return memory.list_sessions()


@app.get("/memory/session/{session_id}")
async def memory_session(session_id: str, request: Request):
    """获取指定会话详情"""
    memory = request.app.state.memory
    data = memory.get_session(session_id)
    if data is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "session not found"}, status_code=404)
    return data


@app.delete("/memory/session/{session_id}")
async def memory_clear_session(session_id: str, request: Request):
    """删除指定会话"""
    memory = request.app.state.memory
    memory.clear_session(session_id)
    return {"status": "ok", "session_id": session_id}


@app.delete("/memory")
async def memory_clear_all(request: Request):
    """清空全部记忆"""
    memory = request.app.state.memory
    memory.clear_all()
    return {"status": "ok", "message": "全部记忆已清空"}


# ── 托管 index.html ──────────────────────────────────────────────────────────
HTML_PATH = Path(__file__).parent.parent / "index.html"

@app.get("/")
async def root():
    if HTML_PATH.exists():
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>index.html not found</h2>")
