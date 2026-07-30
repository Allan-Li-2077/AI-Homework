"""
FastAPI HTTP 服务，提供流式 SSE 接口给 Web UI

接口：
  POST /query/manual  - 手写版 ReAct，流式返回每步
  POST /query/fc      - Function Calling 版，流式返回每步
  POST /chat/manual   - 手写版多轮对话，支持会话历史
  POST /chat/fc       - Function Calling 版多轮对话，支持会话历史
  POST /session/new   - 创建新会话
  GET  /session/{id}  - 获取会话历史
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
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── 会话管理 ──────────────────────────────────────────────────────────────────
class SessionData:
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.history = []  # 存储对话历史: [{"role": "user", "content": ...}, {"role": "assistant", "content": ...}]
        self.created_at = asyncio.get_event_loop().time()

    def add_turn(self, question: str, answer: str):
        """添加一轮对话到历史"""
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": answer})

    def get_history(self) -> list:
        """获取对话历史（不包含system消息）"""
        return self.history.copy()


# 内存存储会话（生产环境应使用Redis等持久化存储）
sessions: dict[str, SessionData] = {}


def get_or_create_session(session_id: Optional[str] = None) -> SessionData:
    """获取或创建会话"""
    if session_id and session_id in sessions:
        return sessions[session_id]
    new_session = SessionData()
    sessions[new_session.id] = new_session
    return new_session


# ── 预加载 FAISS（启动时执行一次）────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("预加载 FAISS 索引和 Embedding 模型...")
    from tools import _load_rag
    await asyncio.to_thread(_load_rag)
    logger.info("预加载完成，服务就绪")
    yield
    # 清理会话（可选）
    sessions.clear()


app = FastAPI(title="ReAct Financial Agent", lifespan=lifespan)


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question:  str
    max_steps: int = 10


class ChatRequest(BaseModel):
    question:    str
    session_id:  Optional[str] = None
    max_steps:   int = 10


class SessionResponse(BaseModel):
    session_id: str
    history:    list
    turn_count: int


# ── SSE 流式生成器 ────────────────────────────────────────────────────────────
def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_react(question: str, max_steps: int, mode: str, conversation_history: list = None):
    """
    同步生成器（react_run）在独立线程中逐步执行，
    每产出一步通过 asyncio.Queue 传递给异步 SSE 生成器，
    实现真正的边思考边推送。

    参数：
      conversation_history: 可选，对话历史，用于多轮对话
    """
    if mode == "manual":
        from react_manual import run as react_run
    else:
        from react_function_calling import run as react_run

    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()
    final_answer_holder = {"answer": None}  # 用于传递最终答案

    def _worker():
        try:
            for step_data in react_run(question, max_steps=max_steps, conversation_history=conversation_history):
                queue.put_nowait(step_data)
                # 捕获最终答案
                if step_data.get("type") == "final":
                    final_answer_holder["answer"] = step_data.get("answer")
        finally:
            queue.put_nowait(_SENTINEL)

    yield _sse({"type": "start", "question": question, "mode": mode})

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _worker)

    while True:
        step_data = await queue.get()
        if step_data is _SENTINEL:
            break
        yield _sse(step_data)

    yield _sse({"type": "done", "final_answer": final_answer_holder["answer"]})


# ── 路由 ──────────────────────────────────────────────────────────────────────

# 单次查询（无会话，兼容已有前端）
@app.post("/query/manual")
async def query_manual(req: QueryRequest):
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "manual"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/query/fc")
async def query_fc(req: QueryRequest):
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "fc"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 多轮对话（带会话管理） ───────────────────────────────────────────────────

@app.post("/session/new")
async def create_session():
    """创建新会话，返回 session_id"""
    session = get_or_create_session()
    return SessionResponse(
        session_id=session.id,
        history=[],
        turn_count=0,
    )


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """获取指定会话的历史记录"""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return SessionResponse(
        session_id=session.id,
        history=session.get_history(),
        turn_count=len(session.history) // 2,
    )


@app.post("/chat/manual")
async def chat_manual(req: ChatRequest):
    """手写版多轮对话，传入 session_id 可继续已有会话"""
    session = get_or_create_session(req.session_id)

    async def _stream_with_save():
        final_answer = None
        async for sse_data in _stream_react(
            req.question, req.max_steps, "manual",
            conversation_history=session.get_history(),
        ):
            # 捕获 final_answer
            if sse_data.startswith("data: "):
                try:
                    parsed = json.loads(sse_data[6:])
                    if parsed.get("type") == "done":
                        final_answer = parsed.get("final_answer")
                except json.JSONDecodeError:
                    pass
            yield sse_data
        # 流结束，保存对话历史
        if final_answer:
            session.add_turn(req.question, final_answer)

    return StreamingResponse(
        _stream_with_save(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session.id,
        },
    )


@app.post("/chat/fc")
async def chat_fc(req: ChatRequest):
    """Function Calling 版多轮对话，传入 session_id 可继续已有会话"""
    session = get_or_create_session(req.session_id)

    async def _stream_with_save():
        final_answer = None
        async for sse_data in _stream_react(
            req.question, req.max_steps, "fc",
            conversation_history=session.get_history(),
        ):
            # 捕获 final_answer
            if sse_data.startswith("data: "):
                try:
                    parsed = json.loads(sse_data[6:])
                    if parsed.get("type") == "done":
                        final_answer = parsed.get("final_answer")
                except json.JSONDecodeError:
                    pass
            yield sse_data
        # 流结束，保存对话历史
        if final_answer:
            session.add_turn(req.question, final_answer)

    return StreamingResponse(
        _stream_with_save(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session.id,
        },
    )


# ── 工具 ──────────────────────────────────────────────────────────────────────

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
