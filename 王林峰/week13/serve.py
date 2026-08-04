"""
FastAPI HTTP 服务 — 带 SSE 事件流的可视化后端
新增：Harness 渐进式分步接口、断点续跑、快照/回滚接口、progressive 分步流式事件
教学重点：
  1. SSE 事件流将四层记忆的每个步骤实时推送到前端
  2. /flush 接口支持单步执行、断点续跑、完整渐进流程
  3. /harness/* 全套调试接口：分步加载、快照、回滚、执行追踪
  4. lifespan 模式：索引/DB 在启动时加载一次，请求间复用
使用方式：
  uvicorn src.serve:app --host 0.0.0.0 --port 8000
接口：
  POST /chat     SSE 流式对话（支持 ?progressive=true 渐进加载）
  POST /flush    SSE 流式 Memory Flush（支持单步/断点续跑）
  GET  /memories 查看当前记忆状态
  GET  /health   健康检查
  POST /harness/load 渐进分层加载记忆
  POST /harness/flush-step 单步执行 flush
  POST /harness/snapshot 保存记忆快照
  POST /harness/rollback 回滚快照
  GET  /harness/trace 查看分步执行日志
依赖：
  pip install fastapi uvicorn openai faiss-cpu apscheduler
  export DASHSCOPE_API_KEY="sk-xxx"
"""
import os
import sys
import json
import sqlite3
import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent.parent))
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from src.session_db import SessionDB
from src.memory_loader import MemoryLoader
from src.vector_store import VectorStore
from src.fts_store import FTSStore
from src.retrieval import HybridRetriever
from src.memory_flush import MemoryFlusher
from src.llm_config import get_chat_client, current_model_info
from src.heartbeat_parser import HeartbeatParser
from src.scheduler import HeartbeatScheduler
# Harness 新增导入
from src.harness.base_harness import BaseProgressiveHarness, HarnessContext
from src.harness.flush_harness import FlushHarness
from src.harness.memory_harness import MemoryLoadHarness
from src.harness.trace_logger import TraceLogger
from src.reset import cmd_backup, cmd_restore, _do_factory_reset

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── 全局单例 ─────────────────────────────────────────────────────────────────
db: SessionDB = None
loader: MemoryLoader = None
vs: VectorStore = None
fts: FTSStore = None
retriever: HybridRetriever = None
flusher: MemoryFlusher = None
current_session_id: int = None
hb_parser: HeartbeatParser = None
hb_scheduler: HeartbeatScheduler = None
# Harness 全局实例
flush_harness: FlushHarness = None
mem_harness: MemoryLoadHarness = None
trace_logger: TraceLogger = None

# ── SSE 广播：每个连接一个 Queue，调度器触发时 broadcast 推给所有连接 ──────────
_stream_listeners: list[asyncio.Queue] = []
async def broadcast(event_type: str, data: dict):
    payload = sse_event(event_type, data)
    logger.info(f"[broadcast] {event_type}，当前监听数：{len(_stream_listeners)}")
    for q in list(_stream_listeners):
        try:
            await q.put(payload)
        except asyncio.QueueFull:
            logger.warning("[broadcast] 队列已满，丢弃一条消息")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, loader, vs, fts, retriever, flusher, current_session_id, hb_parser, hb_scheduler
    global flush_harness, mem_harness, trace_logger
    db = SessionDB()
    loader = MemoryLoader()
    vs = VectorStore()
    fts = FTSStore()
    retriever = HybridRetriever(vs, fts)
    flusher = MemoryFlusher()
    hb_parser = HeartbeatParser()
    current_session_id = db.new_session()
    logger.info(f"服务启动，会话 #{current_session_id}")
    logger.info(f"FTS5/BM25 可用：{fts.available}（{'混合检索' if fts.available else '退化为纯向量'})")
    hb_scheduler = HeartbeatScheduler()
    hb_scheduler.start(broadcast)
    logger.info("HEARTBEAT 调度器已启动")
    # 初始化 Harness
    trace_logger = TraceLogger(log_path=Path(__file__).parent.parent / "outputs/harness_trace.log")
    flush_harness = FlushHarness(db=db, flusher=flusher)
    mem_harness = MemoryLoadHarness(db=db, loader=loader, trace_logger=trace_logger)
    yield
    hb_scheduler.stop()
    if current_session_id:
        db.close_session(current_session_id)

app = FastAPI(title="Agent 记忆系统", lifespan=lifespan)

# ── 请求/响应模型 ──────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: int = None
class FlushRequest(BaseModel):
    session_id: int = None
class HarnessStepRequest(BaseModel):
    session_id: int = None
    chunk_size: int = 5
class SnapshotRequest(BaseModel):
    name: str = None
class RollbackRequest(BaseModel):
    name: str
# ── SSE 工具函数 ──────────────────────────────────────────────────────────────
def sse_event(event_type: str, data: dict) -> str:
    payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
    return f"data: {payload}\n\n"

# ── /chat 接口（新增 progressive 渐进加载参数）────────────────────────────────
@app.post("/chat")
async def chat(
    req: ChatRequest,
    progressive: bool = Query(False, description="开启记忆分层渐进加载SSE事件")
):
    sid = req.session_id or current_session_id
    async def stream():
        # 区分渐进加载 / 一次性全量加载
        if progressive:
            # Harness 渐进分层加载
            mem_harness.init_context(session_id=sid)
            async for chunk in mem_harness.run_progressive(mem_harness.step_runner(chunk_size=5)):
                yield sse_event("memory_progressive_chunk", {
                    "layer": chunk.layer_name,
                    "partial_content": chunk.partial_content[:200],
                    "meta": chunk.layer_meta,
                    "finished_layer": chunk.finished
                })
            prompt_result = loader.build_system_prompt(recent_memory_limit=10)
        else:
            # 原有一次性加载逻辑
            prompt_result = loader.build_system_prompt(recent_memory_limit=10)
            layers_info = [
                {"name": l.name, "source": l.source_file, "chars": l.char_count}
                for l in prompt_result.layers
            ]
            yield sse_event("memory_load", {
                "layers": layers_info,
                "total_chars": prompt_result.total_chars,
            })
        await asyncio.sleep(0)
        # Layer 4 混合检索
        semantic_results = retriever.search(req.message, top_k=3)
        yield sse_event("semantic_search", {
            "query": req.message,
            "results": [
                {
                    "category": r.get("category", ""),
                    "title": r.get("title", ""),
                    "content": r.get("content", "")[:120],
                    "score": round(r["score"], 3),
                    "source": r.get("source", ""),
                }
                for r in semantic_results
            ],
        })
        await asyncio.sleep(0)
        # 组装上下文
        semantic_context = ""
        if semantic_results:
            snippets = [f"- [{r['category']}] {r.get('title','')}: {r['content'][:100]}" for r in semantic_results]
            semantic_context = "## 语义检索到的相关记忆\n" + "\n".join(snippets)
        system_prompt = prompt_result.system_prompt
        if semantic_context:
            system_prompt += "\n\n" + semantic_context
        # 会话历史
        history = db.get_session_messages(sid)
        history_for_api = [{"role": m["role"], "content": m["content"]} for m in history]
        yield sse_event("context_assembly", {
            "system_chars": len(system_prompt),
            "history_turns": len(history_for_api),
        })
        await asyncio.sleep(0)
        # LLM 流式生成
        api_messages = (
            [{"role": "system", "content": system_prompt}]
            + history_for_api
            + [{"role": "user", "content": req.message}]
        )
        client, model = get_chat_client()
        stream_resp = client.chat.completions.create(
            model=model, messages=api_messages, temperature=0.7, stream=True
        )
        full_response = ""
        for chunk in stream_resp:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                full_response += delta
                yield sse_event("token", {"text": delta})
        # 持久化消息
        db.add_message(sid, "user", req.message)
        db.add_message(sid, "assistant", full_response)
        msg_count = db.get_message_count(sid)
        yield sse_event("done", {
            "response": full_response,
            "session_id": sid,
            "message_count": msg_count,
            "auto_flush_threshold": 20,
        })
        # 后台调度意图检测
        if hb_parser and hb_parser.may_contain_schedule_intent(req.message):
            asyncio.create_task(_check_schedule_intent(req.message))
    return StreamingResponse(stream(), media_type="text/event-stream")

async def _check_schedule_intent(message: str):
    loop = asyncio.get_event_loop()
    if hb_parser.may_contain_cancel_intent(message):
        task_name = await loop.run_in_executor(None, hb_parser.analyze_and_cancel, message)
        if task_name:
            hb_scheduler._load_tasks()
            await broadcast("heartbeat_task_cancelled", {
                "task_name": task_name,
                "message": f"🚫 已停止定时任务：{task_name}",
            })
            return
    if hb_parser.may_contain_schedule_intent(message):
        task = await loop.run_in_executor(None, hb_parser.analyze_and_write, message)
        if task:
            hb_scheduler._load_tasks()
            await broadcast("heartbeat_task_added", {
                "task_name": task["name"],
                "trigger": task["trigger"],
                "description": task.get("description", ""),
                "message": f"✅ 已为你设置定时任务：{task.get('description', task['name'])}",
            })

# ── /flush 接口（支持渐进分步执行）──────────────────────────────────────────
@app.post("/flush")
async def flush_session(
    req: FlushRequest,
    step_only: bool = Query(False, description="仅执行单个未完成步骤"),
    progressive: bool = Query(False, description="完整渐进分步流式返回")
):
    sid = req.session_id or current_session_id
    async def stream():
        messages = db.get_session_messages(sid)
        yield sse_event("flush_start", {
            "session_id": sid,
            "message_count": len(messages),
            "step_only": step_only,
            "progressive": progressive
        })
        await asyncio.sleep(0)
        if not messages:
            yield sse_event("flush_done", {"error": "会话为空"})
            return
        # 渐进分步模式
        if progressive or step_only:
            flush_harness.init_context(session_id=sid)
            async for step_res in flush_harness.step_runner(messages):
                yield sse_event("flush_step", step_res)
                trace_logger.write_trace(sid, step_res)
                if step_only and step_res["finished"] is False:
                    yield sse_event("flush_pause", {"current_step": step_res["step"]})
                    break
            yield sse_event("flush_done", {"summary": "分步执行完成"})
            return
        # 原有一次性全量 flush
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, flusher.flush, messages, sid)
        yield sse_event("flush_pass1", {
            "user_updates": result.user_updates,
            "count": len(result.user_updates),
        })
        await asyncio.sleep(0)
        yield sse_event("flush_pass2", {
            "new_entries": [
                {"category": e.get("category", ""), "title": e.get("title", ""), "content": e.get("content", "")[:100]}
                for e in result.new_memory_entries
            ],
            "count": len(result.new_memory_entries),
        })
        await asyncio.sleep(0)
        yield sse_event("flush_pass3", {
            "vectorized": result.vectorized_count,
            "total_in_index": vs.total_entries,
        })
        await asyncio.sleep(0)
        if result.compacted:
            yield sse_event("flush_compaction", {
                "before": result.compaction_before,
                "after": result.compaction_after,
            })
            await asyncio.sleep(0)
        db.mark_flushed(sid)
        yield sse_event("flush_done", {
            "error": result.error,
            "summary": result.summary(),
        })
    return StreamingResponse(stream(), media_type="text/event-stream")

# ── Harness 专属接口 ─────────────────────────────────────────────────────────
@app.post("/harness/load")
async def harness_progressive_load(req: HarnessStepRequest):
    sid = req.session_id or current_session_id
    mem_harness.init_context(sid)
    chunks = []
    async for chunk in mem_harness.step_runner(chunk_size=req.chunk_size):
        chunks.append({
            "layer": chunk.layer_name,
            "partial": chunk.partial_content[:300],
            "meta": chunk.layer_meta,
            "layer_finished": chunk.finished
        })
        trace_logger.write_trace(sid, {"type": "memory_load_chunk", "data": chunks[-1]})
    return JSONResponse({"session_id": sid, "chunks": chunks, "total_layers": len(chunks)})

@app.post("/harness/flush-step")
async def harness_single_flush_step(req: HarnessStepRequest):
    sid = req.session_id or current_session_id
    messages = db.get_session_messages(sid)
    flush_harness.init_context(sid)
    output = []
    async for step in flush_harness.step_runner(messages):
        output.append(step)
        break
    trace_logger.write_trace(sid, {"type": "flush_single_step", "data": output[0] if output else {}})
    return JSONResponse({"session_id": sid, "step_result": output})

@app.post("/harness/snapshot")
async def harness_snapshot(req: SnapshotRequest):
    name = cmd_backup(req.name)
    return JSONResponse({"status": "ok", "snapshot_name": name, "msg": "快照保存成功"})

@app.post("/harness/rollback")
async def harness_rollback(req: RollbackRequest):
    cmd_restore(req.name)
    # 重载调度器
    hb_scheduler._load_tasks()
    return JSONResponse({"status": "ok", "snapshot": req.name, "msg": "快照回滚完成"})

@app.get("/harness/trace")
async def harness_get_trace(session_id: int = None, limit: int = Query(100)):
    logs = trace_logger.read_trace(session_id=session_id, limit=limit)
    return JSONResponse({"trace_count": len(logs), "logs": logs})

# ── 原有保留接口 ─────────────────────────────────────────────────────────────
@app.get("/memories")
async def get_memories():
    mem_dir = loader.memory_dir
    def read_md(name):
        p = mem_dir / name
        return p.read_text(encoding="utf-8") if p.exists() else ""
    return JSONResponse({
        "user_md":      read_md("USER.md"),
        "memory_md":    read_md("MEMORY.md"),
        "soul_md":      read_md("SOUL.md"),
        "agents_md":    read_md("AGENTS.md"),
        "heartbeat_md": read_md("HEARTBEAT.md"),
        "entry_count":  loader.get_memory_entry_count(),
        "faiss_total":  vs.total_entries,
        "fts_total":    fts.total_entries,
        "fts_available": fts.available,
        "recent_sessions": db.get_recent_sessions(5),
    })

@app.get("/stream")
async def stream_events():
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _stream_listeners.append(q)
    logger.info(f"[/stream] 新连接，当前监听数：{len(_stream_listeners)}")
    async def generate():
        try:
            tasks = hb_parser.load_tasks() if hb_parser else []
            yield sse_event("heartbeat_connected", {
                "task_count": len(tasks),
                "tasks": [{"name": t["name"], "trigger": t["trigger"],
                            "description": t.get("description", "")} for t in tasks],
            })
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=20.0)
                    yield payload
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if q in _stream_listeners:
                _stream_listeners.remove(q)
            logger.info(f"[/stream] 连接断开，剩余监听数：{len(_stream_listeners)}")
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.post("/reset")
async def reset_to_factory():
    global current_session_id
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _do_factory_reset)
    if hb_scheduler:
        hb_scheduler._load_tasks()
    current_session_id = db.new_session()
    return {"status": "ok", "session_id": current_session_id}

@app.post("/session/new")
async def new_session():
    global current_session_id
    if current_session_id:
        db.close_session(current_session_id)
    current_session_id = db.new_session()
    return {"session_id": current_session_id}

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "session_id": current_session_id,
        "memory_entries": loader.get_memory_entry_count(),
        "faiss_entries": vs.total_entries,
        "fts_entries":   fts.total_entries,
        "fts_available": fts.available,
        "model": current_model_info(),
        "harness_enabled": True
    }

INDEX_HTML = Path(__file__).parent.parent / "index.html"
@app.get("/")
async def root():
    return FileResponse(INDEX_HTML)