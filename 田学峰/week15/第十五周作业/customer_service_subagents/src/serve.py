"""FastAPI + SSE 流式客服可视化后端

事件流：
  start → main_step(主每步) → dispatch(派发，拓扑加节点) →
  subagent_step(各子客服步骤) → subagent_done → final(答复+统计) → done
"""
import json, logging, queue, threading, uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from agents import run_customer_service

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI()
app.mount("/static", StaticFiles(directory="../static"), name="static")


@app.get("/")
async def index():
    return FileResponse("../static/index.html")


@app.get("/health")
async def health():
    import os
    return JSONResponse({
        "deepseek_key": bool(os.getenv("DEEPSEEK_API_KEY")),
        "status": "ready" if os.getenv("DEEPSEEK_API_KEY") else "missing DEEPSEEK_API_KEY",
    })


@app.post("/query")
async def query(req: Request):
    """SSE 流式返回客服处理全过程。Body: {"question": "..."}"""
    body = await req.json()
    question = body.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "question 不能为空"}, status_code=400)

    ev_q: "queue.Queue[dict]" = queue.Queue()

    def emit(event: str, data: dict):
        ev_q.put({"event": event, "data": data})

    def on_main(step):
        emit("main_step", step)

    def on_sub(sid, step):
        emit("subagent_step", {"sid": sid, **step})

    def on_dispatch(info):
        emit("dispatch", info)

    def on_done(sid, dur, topic):
        emit("subagent_done", {"sid": sid, "duration": dur, "subtopic": topic})

    def worker():
        try:
            emit("start", {"question": question})
            r = run_customer_service(question, on_main_step=on_main,
                                     on_subagent_step=on_sub,
                                     on_dispatch=on_dispatch,
                                     on_subagent_done=on_done)
            emit("final", {
                "answer": r["final_answer"],
                "parallel_stats": r["parallel_stats"],
                "n_subagents": len(r["subagents"]),
            })
        except Exception as e:
            logger.exception("worker error")
            emit("error", {"msg": f"{type(e).__name__}: {e}"})
        finally:
            emit("done", {})

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while True:
            ev = ev_q.get()
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"
            if ev["event"] in ("done", "error"):
                break

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    uvicorn.run("serve:app", host="0.0.0.0", port=8003, reload=False)
