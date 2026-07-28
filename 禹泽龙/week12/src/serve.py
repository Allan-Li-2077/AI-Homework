"""
FastAPI HTTP 服务，提供流式 SSE 接口给 Web UI

接口：
  POST /query/manual  - 手写版 ReAct，流式返回每步
  POST /query/fc      - Function Calling 版，流式返回每步
  GET  /health        - 健康检查

使用方式：
  uvicorn serve:app --host 0.0.0.0 --port 8000

  浏览器                              FastAPI 服务                    ReAct Agent
  │                                    │                               │
  │──── POST /query/manual ───────────▶│                               │
  │                                    │                               │
  │  ←── SSE stream (start) ──────────│                               │
  │                                    │ 启动线程                       │
  │                                    │─────────▶ react_run() ──────▶│
  │                                    │                               │  ↓
  │                                    │ ◀──────── step_data ◀────────│  yield 每步
  │  ←── SSE: step_data ──────────────│                               │
  │                                    │                               │
  │  ←── SSE: step_data ──────────────│ ◀─────────────────────────────│
  │  ...                               │                               │
  │  ←── SSE: done ───────────────────│                               │
  │                                    │                               │
SSE 本质：建立"长连接"，服务端可以随时向浏览器推送数据，浏览器通过 EventSource 接收。
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
    # 服务启动时执行一次
    logger.info("预加载 FAISS 索引和 Embedding 模型...")
    from tools import _load_rag
    await asyncio.to_thread(_load_rag)   # 在独立线程中加载，不阻塞
    logger.info("预加载完成，服务就绪")
    yield  # 服务运行中
    # 为什么用 @asynccontextmanager：管理服务生命周期，服务启动时预加载，服务关闭时清理。

# 创建FastAPI应用
app = FastAPI(title="ReAct Financial Agent", lifespan=lifespan)

# 请求数据类型 Pydantic 作用：自动验证请求 JSON 的类型，history: list | None = None 表示可选字段。
# ── 请求/响应模型 ─────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question:  str  # 用户问题
    max_steps: int = 10  # 最大步数
    history: list | None = None  # 多轮对话历史，None 表示新对话

"""
SSE 工具函数
部分	        含义
data:	        SSE 协议固定前缀
json.dumps(...)	把 Python dict 转成 JSON 字符串
\n\n	        两个换行表示一条消息结束
"""
# ── SSE 流式生成器 ────────────────────────────────────────────────────────────
def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

# 核心作用：把同步的 ReAct 生成器转换成异步的 SSE 流。
async def _stream_react(question: str, max_steps: int, mode: str, history: list | None = None):
    """
    同步生成器（react_run）在独立线程中逐步执行，
    每产出一步通过 asyncio.Queue 传递给异步 SSE 生成器，
    实现真正的边思考边推送。

    参数：
      question: 当前用户问题
      max_steps: 最大步数限制
      mode: "manual" 或 "fc"
      history: 可选的对话历史，用于多轮对话
    """
    if mode == "manual":
        from react_manual import run as react_run
    else:
        from react_function_calling import run as react_run

    """
    问题：react_run() 是同步阻塞的，但 FastAPI 需要异步响应
    解决：用 Thread + Queue 桥接
    react_run (同步)  →  Queue  →  SSE yield (异步)  →  浏览器
    ↓
    阻塞执行       放入数据    非阻塞取出
    """
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _worker():
        try:
            # react_run 是生成器，逐步yield每一步的结果
            for step_data in react_run(question, max_steps=max_steps, messages=history):
                queue.put_nowait(step_data)# 放入队列
        finally:
            queue.put_nowait(_SENTINEL)
    # 1.发送开始信号
    yield _sse({"type": "start", "question": question, "mode": mode})

    loop = asyncio.get_event_loop()
    # 2.启动工作线程
    loop.run_in_executor(None, _worker)

    # 3.循环队列取数据
    while True:
        # 等数据（非阻塞）
        step_data = await queue.get()
        # 是结束标记？
        if step_data is _SENTINEL:
            # 退出循环
            break
        # 发送数据给浏览器
        yield _sse(step_data)

    # 4.发送结束信号
    yield _sse({"type": "done"})

"""
StreamingResponse：流式响应，数据不是一次性返回，而是分批发送。

路由	                 作用
POST /query/manual	    手写版 ReAct，流式返回
POST /query/fc	        Function Calling 版，流式返回
GET /health	            健康检查，返回模型名
"""
# ── 路由 ──────────────────────────────────────────────────────────────────────
@app.post("/query/manual")
async def query_manual(req: QueryRequest):
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "manual", req.history),
        media_type="text/event-stream",       # 告诉浏览器这是SSE
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},       #不缓存
    )


@app.post("/query/fc")
async def query_fc(req: QueryRequest):
    return StreamingResponse(
        _stream_react(req.question, req.max_steps, "fc", req.history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model": os.getenv("AGENT_MODEL", "qwen-max")}


# ── 托管 index.html ──────────────────────────────────────────────────────────
HTML_PATH = Path(__file__).parent.parent / "index.html"
# 访问 http://localhost:8000/ 时，返回 index.html 的内容。
@app.get("/")
async def root():
    if HTML_PATH.exists():
        return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>index.html not found</h2>")
