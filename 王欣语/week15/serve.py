"""
FastAPI + SSE 流式服务

提供 HTTP 接口和 Web 可视化页面：
- POST /query: 接收问题，SSE 流式返回调研过程
- GET /: 返回可视化页面
"""

import os
import sys
import json
import asyncio
import logging
from queue import Queue
from threading import Thread

from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from agents import run_research

logger = logging.getLogger(__name__)
app = FastAPI(title="Subagent 并行调研系统")

# 尝试挂载静态文件（如果有 static 目录）
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/health")
def health():
    """健康检查"""
    return {"status": "ok", "llm": "deepseek-chat", "search": "tavily"}


@app.post("/query")
def query_endpoint(payload: dict):
    """
    接收问题，SSE 流式返回调研过程
    
    Request: {"question": "..."}
    Response: SSE 流，事件类型：
        - start: 开始
        - main_step: 主 agent 每步
        - dispatch: 派发 subagent
        - subagent_step: subagent 每步
        - subagent_done: subagent 完成
        - final: 最终报告
        - done: 结束
    """
    question = payload.get("question", "")
    if not question:
        return {"error": "question 不能为空"}

    event_queue = Queue()

    def on_main_step(step):
        event_queue.put(("main_step", step))

    def on_subagent_step(sid, step):
        event_queue.put(("subagent_step", {"sid": sid, **step}))

    def on_subagent_done(sid, duration, topic):
        event_queue.put(("subagent_done", {"sid": sid, "duration": duration, "topic": topic}))

    def on_dispatch(info):
        event_queue.put(("dispatch", info))

    def run_in_thread():
        try:
            result = run_research(
                question,
                on_main_step=on_main_step,
                on_subagent_step=on_subagent_step,
                on_subagent_done=on_subagent_done,
                on_dispatch=on_dispatch
            )
            event_queue.put(("final", {
                "final_answer": result["final_answer"],
                "parallel_stats": result["parallel_stats"]
            }))
        except Exception as e:
            event_queue.put(("error", {"message": str(e)}))
        finally:
            event_queue.put(("done", {}))

    # 启动后台线程执行调研
    thread = Thread(target=run_in_thread)
    thread.start()

    def event_generator():
        """SSE 事件生成器"""
        yield f"event: start\ndata: {json.dumps({'question': question})}\n\n"
        
        while True:
            event_type, data = event_queue.get()
            yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if event_type in ("done", "error"):
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@app.get("/", response_class=HTMLResponse)
def index():
    """返回简单的可视化页面"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Subagent 并行调研系统</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 {
            text-align: center;
            margin-bottom: 30px;
            background: linear-gradient(90deg, #00d4ff, #7b2cbf);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .input-area {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        input {
            flex: 1;
            padding: 12px 16px;
            border: 1px solid #333;
            border-radius: 8px;
            background: rgba(255,255,255,0.05);
            color: #e0e0e0;
            font-size: 14px;
        }
        button {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            background: linear-gradient(90deg, #00d4ff, #7b2cbf);
            color: white;
            cursor: pointer;
            font-size: 14px;
        }
        button:hover { opacity: 0.9; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        .output {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 20px;
            min-height: 200px;
            white-space: pre-wrap;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.6;
        }
        .step {
            margin-bottom: 12px;
            padding: 10px;
            border-radius: 8px;
            background: rgba(255,255,255,0.03);
        }
        .step-main { border-left: 3px solid #00d4ff; }
        .step-sub { border-left: 3px solid #7b2cbf; }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            margin-right: 8px;
        }
        .badge-main { background: #00d4ff; color: #1a1a2e; }
        .badge-sub { background: #7b2cbf; color: white; }
        .stats {
            margin-top: 20px;
            padding: 15px;
            background: rgba(0,212,255,0.1);
            border-radius: 8px;
            border: 1px solid rgba(0,212,255,0.3);
        }
        .final-answer {
            margin-top: 20px;
            padding: 20px;
            background: rgba(123,44,191,0.1);
            border-radius: 8px;
            border: 1px solid rgba(123,44,191,0.3);
            white-space: pre-wrap;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Subagent 并行调研系统</h1>
        <div class="input-area">
            <input type="text" id="question" 
                placeholder="输入调研问题，例如：2024年中国新能源汽车市场调研：销量规模、主要厂商竞争格局、政策趋势"
                value="2024年中国新能源汽车市场调研：销量规模、主要厂商竞争格局、政策趋势">
            <button onclick="startResearch()" id="btn">开始调研</button>
        </div>
        <div class="output" id="output"></div>
    </div>

    <script>
        async function startResearch() {
            const question = document.getElementById('question').value;
            const btn = document.getElementById('btn');
            const output = document.getElementById('output');
            
            if (!question) return;
            
            btn.disabled = true;
            output.innerHTML = '<div class="step">正在连接...</div>';
            
            try {
                const response = await fetch('/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ question })
                });
                
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                let steps = [];
                let finalAnswer = '';
                let stats = null;
                
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n\n');
                    buffer = lines.pop() || '';
                    
                    for (const chunk of lines) {
                        const eventMatch = chunk.match(/^event: ([\\w]+)/);
                        const dataMatch = chunk.match(/^data: (.+)/m);
                        
                        if (eventMatch && dataMatch) {
                            const eventType = eventMatch[1];
                            const data = JSON.parse(dataMatch[1]);
                            
                            if (eventType === 'main_step') {
                                steps.push({
                                    type: 'main',
                                    agent: data.agent,
                                    action: data.action,
                                    thought: data.thought,
                                    observation: data.observation
                                });
                            } else if (eventType === 'subagent_step') {
                                steps.push({
                                    type: 'sub',
                                    agent: data.sid,
                                    action: data.action,
                                    thought: data.thought,
                                    observation: data.observation
                                });
                            } else if (eventType === 'dispatch') {
                                steps.push({
                                    type: 'dispatch',
                                    subtopics: data.subtopics,
                                    subagent_ids: data.subagent_ids
                                });
                            } else if (eventType === 'subagent_done') {
                                steps.push({
                                    type: 'sub_done',
                                    sid: data.sid,
                                    duration: data.duration,
                                    topic: data.topic
                                });
                            } else if (eventType === 'final') {
                                finalAnswer = data.final_answer;
                                stats = data.parallel_stats;
                            }
                            
                            renderOutput();
                        }
                    }
                }
                
                function renderOutput() {
                    let html = '';
                    
                    for (const step of steps) {
                        if (step.type === 'main') {
                            html += `<div class="step step-main">
                                <span class="badge badge-main">主Agent</span>
                                <strong>${step.action}</strong>
                                ${step.thought ? `<br>Thought: ${step.thought}` : ''}
                                ${step.observation ? `<br>Observation: ${step.observation.substring(0, 200)}...` : ''}
                            </div>`;
                        } else if (step.type === 'sub') {
                            html += `<div class="step step-sub">
                                <span class="badge badge-sub">${step.agent}</span>
                                <strong>${step.action}</strong>
                                ${step.thought ? `<br>Thought: ${step.thought}` : ''}
                                ${step.observation ? `<br>Observation: ${step.observation.substring(0, 150)}...` : ''}
                            </div>`;
                        } else if (step.type === 'dispatch') {
                            html += `<div class="step" style="border-left: 3px solid #ffd700;">
                                <span class="badge" style="background: #ffd700; color: #1a1a2e;">派发</span>
                                派发 ${step.subtopics.length} 个子任务: ${step.subtopics.join(' | ')}
                            </div>`;
                        } else if (step.type === 'sub_done') {
                            html += `<div class="step" style="border-left: 3px solid #00ff88;">
                                <span class="badge" style="background: #00ff88; color: #1a1a2e;">完成</span>
                                ${step.sid} 完成 (${step.duration}s): ${step.topic}
                            </div>`;
                        }
                    }
                    
                    if (stats && stats.length > 0) {
                        const s = stats[0];
                        html += `<div class="stats">
                            <strong>并行统计:</strong><br>
                            子Agent数: ${s.n_subagents} | 并行耗时: ${s.wall_clock}s | 
                            串行预估: ${s.serial_sum}s | 加速比: ${s.speedup}×
                        </div>`;
                    }
                    
                    if (finalAnswer) {
                        html += `<div class="final-answer">
                            <strong>最终报告:</strong><br><br>${finalAnswer}
                        </div>`;
                    }
                    
                    output.innerHTML = html;
                    output.scrollTop = output.scrollHeight;
                }
                
            } catch (e) {
                output.innerHTML = `<div class="step" style="color: #ff6b6b;">错误: ${e.message}</div>`;
            } finally {
                btn.disabled = false;
            }
        }
    </script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
