"""
代码审查 Subagent HTTP 服务（FastAPI + SSE 流式）

教学重点：
  SSE 逐事件推送，前端实时看到：
  - 主审查 agent 的 ReAct 每步（Thought/Action/Observation）
  - 派发维度审查员时拓扑加节点
  - 各维度审查员并行 ReAct 步骤
  - 最终审查报告 + 并行加速统计

启动：
  uvicorn src.serve:app --host 0.0.0.0 --port 8003
  浏览器开 http://localhost:8003

  审查其他项目：PROJECT_ROOT=/path/to/project uvicorn src.serve:app --port 8003

依赖：pip install fastapi uvicorn
"""
import os
import sys
import json
import queue
import threading
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("代码审查 subagent 服务就绪")
    project_root = os.getenv("PROJECT_ROOT", str(BASE_DIR.parent))
    logger.info(f"审查项目根目录: {project_root}")
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ReviewRequest(BaseModel):
    question: str
    project: str = ""  # 可选：指定要审查的项目路径（覆盖 PROJECT_ROOT）


@app.get("/health")
def health():
    has_deepseek = bool(os.getenv("DEEPSEEK_API_KEY"))
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    project_root = os.getenv("PROJECT_ROOT", os.getcwd())
    return {
        "status": "ok",
        "deepseek": has_deepseek,
        "anthropic": has_anthropic,
        "project_root": str(project_root),
    }


@app.post("/review")
def review(req: ReviewRequest):
    """SSE 流式：主审查 agent + 各维度审查员的 ReAct 步骤逐事件推送。"""

    # 如果请求指定了 project，临时设置
    if req.project:
        os.environ["PROJECT_ROOT"] = req.project

    import agents

    def event_stream():
        q = queue.Queue()
        SENTINEL = object()

        def push(ev):
            q.put(ev)

        def on_main_step(step):
            push({"type": "main_step", **step})

        def on_dispatch(info):
            push({"type": "dispatch", **info})

        def on_subagent_step(sid, step):
            push({"type": "subagent_step", "subagent_id": sid, **step})

        def on_subagent_done(sid, duration, dimension_name):
            push({
                "type": "subagent_done",
                "subagent_id": sid,
                "duration": duration,
                "subtopic": dimension_name,
            })

        def run():
            try:
                r = agents.run_review(
                    req.question,
                    on_main_step=on_main_step,
                    on_dispatch=on_dispatch,
                    on_subagent_step=on_subagent_step,
                    on_subagent_done=on_subagent_done,
                )
                push({
                    "type": "final",
                    "answer": r["final_answer"],
                    "parallel_stats": r["parallel_stats"],
                    "main_trace_len": len(r["main_trace"]),
                    "subagent_count": len(r["subagents"]),
                })
            except Exception as e:
                import traceback
                push({
                    "type": "error",
                    "message": f"{type(e).__name__}: {str(e)[:200]}",
                })
                logger.error(f"审查失败: {traceback.format_exc()}")
            finally:
                push(SENTINEL)

        threading.Thread(target=run, daemon=True).start()

        # 先发 start
        yield "data: " + json.dumps({
            "type": "start",
            "question": req.question,
            "project": os.getenv("PROJECT_ROOT", ""),
        }, ensure_ascii=False) + "\n\n"

        while True:
            ev = q.get()
            if ev is SENTINEL:
                yield "data: " + json.dumps(
                    {"type": "done"}, ensure_ascii=False
                ) + "\n\n"
                break
            yield "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("serve:app", host="0.0.0.0", port=8003, reload=False)
