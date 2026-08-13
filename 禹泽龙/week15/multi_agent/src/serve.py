"""
FastAPI + SSE 流式服务 - 调试版
"""
import json
import os
import uuid
import asyncio
import logging
import sys
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 调试日志
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Multi-Agent System", version="1.0.0")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    query: str
    session_id: str = ""


@app.get("/", response_class=HTMLResponse)
async def index():
    path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Multi-Agent System</h1>"


@app.post("/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    logger.info(f"[{session_id}] 收到请求: {request.query[:50]}...")

    q: asyncio.Queue = asyncio.Queue()
    SENTINEL = "__DONE__"

    # ── 回调函数 ──────────────────────────────────────────────────────────

    def on_main_step(step: dict):
        print(f"[DEBUG on_main_step] session={session_id} action={step.get('action')} thought={str(step.get('thought',''))[:50]}")
        logger.info(f"[{session_id}] main_step: action={step.get('action')}, thought={str(step.get('thought',''))[:50]}...")
        q.put_nowait({"type": "main_step", **step})

    def on_dispatch(subtopics: list, subagent_ids: list):
        logger.info(f"[{session_id}] dispatch: {len(subtopics)} tasks -> {subagent_ids}")
        q.put_nowait({"type": "dispatch", "subtopics": subtopics, "subagent_ids": subagent_ids})

    def on_subagent_start(sid: str, topic: str):
        logger.info(f"[{session_id}] subagent_start: {sid} = {topic[:30]}...")
        q.put_nowait({"type": "subagent_start", "subagent_id": sid, "topic": topic})

    def on_subagent_step(sid: str, step: dict):
        logger.info(f"[{session_id}] sub_step {sid}: action={step.get('action')}")
        q.put_nowait({"type": "subagent_step", "subagent_id": sid, **step})

    def on_subagent_done(sid: str, duration: float, topic: str,
                         error: str = None, steps: list = None, final_answer: str = None):
        logger.info(f"[{session_id}] subagent_done: {sid} dur={duration:.2f}s err={error}")
        q.put_nowait({"type": "subagent_done", "subagent_id": sid, "duration": duration,
              "topic": topic, "error": error,
              "steps": steps or [], "final_answer": final_answer or ""})

    def on_dispatch_result(wall_clock: float, serial_sum: float,
                           speedup: float, n_tasks: int):
        logger.info(f"[{session_id}] dispatch_result: wall={wall_clock:.2f}s serial={serial_sum:.2f}s speedup={speedup:.2f}x tasks={n_tasks}")
        q.put_nowait({"type": "dispatch_result", "parallel_time": wall_clock,
              "serial_sum": serial_sum, "speedup": speedup, "task_count": n_tasks})

    def on_synthesis_start():
        logger.info(f"[{session_id}] synthesis_start")
        q.put_nowait({"type": "synthesis_start"})

    def on_main_done():
        logger.info(f"[{session_id}] main_done")
        q.put_nowait({"type": "main_done"})

    def on_final_answer(answer: str):
        logger.info(f"[{session_id}] final_answer: {answer[:80]}...")
        q.put_nowait({"type": "final_answer", "answer": answer})

    # ── 后台线程跑同步 agent ─────────────────────────────────────────
    def run():
        logger.info(f"[{session_id}] 线程启动")
        try:
            if BASE_DIR not in sys.path:
                sys.path.insert(0, BASE_DIR)
            from src.agents import run_research
            logger.info(f"[{session_id}] run_research 开始")
            run_research(
                question=request.query,
                on_main_step=on_main_step,
                on_dispatch=on_dispatch,
                on_subagent_start=on_subagent_start,
                on_subagent_step=on_subagent_step,
                on_subagent_done=on_subagent_done,
                on_dispatch_result=on_dispatch_result,
                on_synthesis_start=on_synthesis_start,
                on_main_done=on_main_done,
                on_final_answer=on_final_answer,
            )
            logger.info(f"[{session_id}] run_research 完成")
        except Exception as e:
            import traceback
            logger.exception(f"[{session_id}] Agent 异常: {e}")
            logger.error(f"[{session_id}] 堆栈: {traceback.format_exc()}")
            q.put_nowait({"type": "error", "message": f"{type(e).__name__}: {str(e)}"})
        finally:
            logger.info(f"[{session_id}] 发送 SENTINEL")
            q.put_nowait(SENTINEL)

    import threading
    threading.Thread(target=run, daemon=True).start()
    logger.info(f"[{session_id}] 线程已启动，等待事件...")

    # ── async generator ────────────────────────────────────────────────
    async def event_generator():
        logger.info(f"[{session_id}] SSE 开始推送")
        yield f"data: {json.dumps({'type': 'start', 'session_id': session_id}, ensure_ascii=False)}\n\n"

        while True:
            ev = await q.get()
            print(f"[DEBUG SSE yield] session={session_id} ev={str(ev)[:100]}")
            logger.info(f"[{session_id}] 获取到事件: {str(ev)[:80]}")
            if ev == SENTINEL:
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                logger.info(f"[{session_id}] SSE 结束")
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/chat/{session_id}")
async def get_session(session_id: str):
    return {"session_id": session_id, "status": "active"}


def run_server(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    run_server()
