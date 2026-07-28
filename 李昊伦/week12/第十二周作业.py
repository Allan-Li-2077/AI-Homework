"""
多轮对话版 Function Calling ReAct Agent

基于 react_function_calling.py 改造，核心变化：
  1. 新增 ConversationSession 类，messages 从函数局部变量变为 Session 持久属性
  2. 每轮 Final Answer 后将结果追回 messages，保留上下文供后续轮次引用
  3. 新增 SessionManager 管理多个会话的生命周期
  4. 内置 FastAPI 服务，提供多轮对话的 HTTP 接口

使用方式：
  # CLI 多轮交互模式
  python react_fc_multiturn.py

  # 启动 Web 服务（多轮对话版）
  python react_fc_multiturn.py --serve
  python react_fc_multiturn.py --serve --port 8000

环境变量：
  DASHSCOPE_API_KEY 或 DEEPSEEK_API_KEY  必填其一
  AGENT_MODEL  可选，默认 deepseek-v4-flash
"""

import os
import sys
import json
import time
import uuid
import logging
import argparse
import asyncio
from pathlib import Path
from typing import Generator
from contextlib import asynccontextmanager

from openai import OpenAI

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ── LLM 客户端 ────────────────────────────────────────────────────────────────
# 与原 react_function_calling.py 保持一致，自动适配 DASHSCOPE / DEEPSEEK
if os.getenv("DASHSCOPE_API_KEY"):
    client = OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    MODEL = os.getenv("AGENT_MODEL", "qwen-max")
else:
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )
    MODEL = os.getenv("AGENT_MODEL", "deepseek-v4-flash")

FC_SYSTEM_PROMPT = """你是一个专业的A股金融分析助手，正在进行多轮对话。
规则：
- 调用 financial_indicator 或 stock_price 之前，必须先用 company_lookup 获取股票代码
- 数字计算必须使用 calculator 工具，不能心算
- Final Answer 必须引用具体数据来源
- 如果没有合适工具能回答，直接说明原因
- 你可以引用之前对话轮次中的结论，用户说"那XX呢"之类的追问时，结合上下文理解
"""


# ══════════════════════════════════════════════════════════════════════════════
#  核心：ConversationSession（多轮对话会话）
# ══════════════════════════════════════════════════════════════════════════════

class ConversationSession:
    """
    一个多轮对话会话。

    与原 run() 函数的唯一本质区别：
      - 原来：messages 是函数局部变量，函数结束即销毁
      - 现在：messages 是 Session 的实例属性，跨轮次持久存在

    ReAct 循环逻辑（Thought → Action → Observation）完全不变。
    """

    def __init__(self, session_id: str, system_prompt: str = FC_SYSTEM_PROMPT):
        self.session_id = session_id
        self.messages = [
            {"role": "system", "content": system_prompt}
        ]
        self.history = []           # 每轮的结构化记录（供前端展示和调试）
        self.turn_count = 0
        self.max_turns = 20         # 最大对话轮数
        self.created_at = time.time()
        self.last_active = time.time()

    def run(self, question: str, max_steps: int = 10) -> Generator[dict, None, None]:
        """
        执行一轮多轮 ReAct 循环。

        与原 react_function_calling.run() 的区别仅 3 处（标注 ★）：
          1. ★ 不新建 messages，追加用户问题到 self.messages
          2. ★ Final Answer 后追回 self.messages（保留上下文）
          3. ★ 记录到 self.history
        """
        from tools import TOOLS_MAP, TOOLS_SCHEMA

        self.turn_count += 1
        self.last_active = time.time()

        # ★ 改动 1：追加用户问题到持久化的 messages
        self.messages.append({"role": "user", "content": question})

        turn_record = {
            "turn": self.turn_count,
            "question": question,
            "steps": [],
            "answer": None,
            "elapsed_s": 0,
        }
        start = time.time()

        for step in range(1, max_steps + 1):
            response = client.chat.completions.create(
                model=MODEL,
                messages=self.messages,       # ← 包含全部历史上下文
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                temperature=0,
            )
            msg = response.choices[0].message
            reason = response.choices[0].finish_reason

            # 模型决定直接回答（无工具调用）
            if reason == "stop" or not msg.tool_calls:
                answer = msg.content or "（模型返回空内容）"

                # ★ 改动 2：把 Final Answer 追回 messages，保留上下文
                self.messages.append({"role": "assistant", "content": answer})

                turn_record["answer"] = answer
                turn_record["elapsed_s"] = round(time.time() - start, 1)
                # ★ 改动 3：记录到 history
                self.history.append(turn_record)

                yield {
                    "turn":  self.turn_count,
                    "step":  step,
                    "type":  "final",
                    "thought": "",
                    "answer": answer,
                }
                return

            # 模型请求调用工具（逻辑与原版完全一致）
            self.messages.append(msg)

            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                tool_fn = TOOLS_MAP.get(tool_name)
                if tool_fn is None:
                    observation = f"未知工具 '{tool_name}'"
                else:
                    try:
                        observation = tool_fn(**tool_args)
                    except TypeError as e:
                        observation = f"工具参数错误: {e}"

                step_result = {
                    "turn":         self.turn_count,
                    "step":         step,
                    "type":         "action",
                    "thought":      "",
                    "action":       tool_name,
                    "action_input": tool_args,
                    "observation":  str(observation),
                }
                turn_record["steps"].append(step_result)
                yield step_result

                self.messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      str(observation),
                })

        # 超出最大步数
        turn_record["answer"] = f"已达最大步数 {max_steps}，未能得出最终答案"
        turn_record["elapsed_s"] = round(time.time() - start, 1)
        self.history.append(turn_record)

        yield {
            "turn":  self.turn_count,
            "step":  max_steps + 1,
            "type":  "max_steps",
            "answer": turn_record["answer"],
        }

    def get_summary(self) -> dict:
        """返回会话摘要（供 API 使用）"""
        return {
            "session_id":  self.session_id,
            "turn_count":  self.turn_count,
            "messages_len": len(self.messages),
            "created_at":  self.created_at,
            "last_active": self.last_active,
            "history":     self.history,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  SessionManager（会话生命周期管理）
# ══════════════════════════════════════════════════════════════════════════════

class SessionManager:
    """管理多个 ConversationSession 的创建、查询和清理"""

    def __init__(self, ttl_seconds: int = 3600):
        self.sessions: dict[str, ConversationSession] = {}
        self.ttl_seconds = ttl_seconds  # 会话过期时间（默认1小时）

    def create(self) -> str:
        """创建新会话，返回 session_id"""
        self._cleanup_expired()
        session_id = uuid.uuid4().hex[:8]
        self.sessions[session_id] = ConversationSession(session_id=session_id)
        logger.info(f"会话已创建: {session_id}")
        return session_id

    def get(self, session_id: str) -> ConversationSession | None:
        """获取会话，不存在或已过期返回 None"""
        session = self.sessions.get(session_id)
        if session is None:
            return None
        if time.time() - session.last_active > self.ttl_seconds:
            del self.sessions[session_id]
            return None
        session.last_active = time.time()
        return session

    def delete(self, session_id: str):
        """删除会话"""
        self.sessions.pop(session_id, None)

    def list_sessions(self) -> list[dict]:
        """列出所有活跃会话"""
        self._cleanup_expired()
        return [s.get_summary() for s in self.sessions.values()]

    def _cleanup_expired(self):
        """清理过期会话"""
        now = time.time()
        expired = [
            sid for sid, s in self.sessions.items()
            if now - s.last_active > self.ttl_seconds
        ]
        for sid in expired:
            del self.sessions[sid]
        if expired:
            logger.info(f"已清理 {len(expired)} 个过期会话")


# ══════════════════════════════════════════════════════════════════════════════
#  CLI 多轮交互模式
# ══════════════════════════════════════════════════════════════════════════════

COLORS = {
    "thought": "\033[36m",
    "action":  "\033[33m",
    "obs":     "\033[32m",
    "final":   "\033[35m",
    "error":   "\033[31m",
    "info":    "\033[34m",
    "reset":   "\033[0m",
}

def _c(color: str, text: str) -> str:
    return f"{COLORS[color]}{text}{COLORS['reset']}"


def cli_interactive():
    """CLI 多轮交互模式"""
    session = ConversationSession(session_id="cli")

    print(f"\n{'='*60}")
    print(f"  ReAct Financial Agent — 多轮对话模式")
    print(f"  模型: {MODEL}  实现: Function Calling")
    print(f"  输入 'quit' 退出  |  'new' 重新开始  |  'history' 查看历史")
    print(f"{'='*60}")

    while True:
        try:
            question = input(f"\n{_c('info', f'[第{session.turn_count + 1}轮]')} 请输入问题: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{_c('info', '再见！')}")
            break

        if not question:
            continue
        if question.lower() == "quit":
            print(_c("info", "再见！"))
            break
        if question.lower() == "new":
            session = ConversationSession(session_id="cli")
            print(_c("info", "已开启新对话"))
            continue
        if question.lower() == "history":
            if not session.history:
                print(_c("info", "暂无对话历史"))
            for h in session.history:
                turn_num = h['turn']
                print(f"\n  {_c('info', f'Turn {turn_num}')}: {h['question']}")
                print(f"  答案: {h['answer'][:200]}...")
                print(f"  步骤: {len(h['steps'])}步  耗时: {h['elapsed_s']}s")
            continue

        start = time.time()
        action_count = 0

        for step_data in session.run(question):
            stype = step_data["type"]

            if stype == "action":
                action_count += 1
                sd = step_data
                print(f"\n  [{_c('info', 'Turn ' + str(sd['turn']))} | Step {sd['step']}]")
                print(f"  {_c('thought', 'Thought: (模型内部推理)')}")
                print(f"  {_c('action',  'Action:  ' + sd['action'])}")
                print(f"  {_c('action',  'Input:   ' + json.dumps(sd['action_input'], ensure_ascii=False))}")
                obs_text = sd["observation"][:200]
                print(f"  {_c('obs',     'Obs:     ' + obs_text)}")

            elif stype == "final":
                elapsed = time.time() - start
                sd = step_data
                print(f"\n  {'─'*50}")
                print(f"  {_c('final', 'Final Answer (Turn ' + str(sd['turn']) + '):')}")
                print(f"  {sd['answer']}")
                print(f"  共 {action_count} 步，耗时 {elapsed:.1f}s")

            elif stype in ("error", "max_steps"):
                print(f"  {_c('error', step_data.get('answer', ''))}")


# ══════════════════════════════════════════════════════════════════════════════
#  FastAPI Web 服务
# ══════════════════════════════════════════════════════════════════════════════

def create_app():
    """创建 FastAPI 应用（工厂函数，便于测试）"""
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, StreamingResponse
    from pydantic import BaseModel

    session_mgr = SessionManager(ttl_seconds=3600)

    @asynccontextmanager
    async def lifespan(app):
        logger.info("多轮对话服务启动，预加载 FAISS 索引...")
        from tools import _load_rag
        await asyncio.to_thread(_load_rag)
        logger.info("预加载完成，服务就绪")
        yield

    app = FastAPI(title="ReAct Financial Agent (Multi-Turn)", lifespan=lifespan)

    # ── 请求模型 ──────────────────────────────────────────────────────────────
    class QueryRequest(BaseModel):
        session_id: str
        question:   str
        max_steps:  int = 10

    # ── SSE 工具函数 ──────────────────────────────────────────────────────────
    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    # ── 流式生成器 ────────────────────────────────────────────────────────────
    async def _stream_multiturn(session: ConversationSession,
                                 question: str, max_steps: int):
        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        def _worker():
            try:
                for step_data in session.run(question, max_steps=max_steps):
                    queue.put_nowait(step_data)
            finally:
                queue.put_nowait(_SENTINEL)

        yield _sse({
            "type": "start",
            "question": question,
            "session_id": session.session_id,
            "turn": session.turn_count,
        })

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _worker)

        while True:
            step_data = await queue.get()
            if step_data is _SENTINEL:
                break
            yield _sse(step_data)

        yield _sse({"type": "done"})

    # ── 路由：会话管理 ────────────────────────────────────────────────────────
    @app.post("/session/new")
    async def new_session():
        sid = session_mgr.create()
        return {"session_id": sid}

    @app.get("/session/{session_id}")
    async def get_session(session_id: str):
        session = session_mgr.get(session_id)
        if not session:
            return {"error": "会话不存在或已过期"}
        return session.get_summary()

    @app.delete("/session/{session_id}")
    async def delete_session(session_id: str):
        session_mgr.delete(session_id)
        return {"status": "deleted"}

    @app.get("/sessions")
    async def list_sessions():
        return {"sessions": session_mgr.list_sessions()}

    # ── 路由：多轮对话查询 ────────────────────────────────────────────────────
    @app.post("/query")
    async def query(req: QueryRequest):
        session = session_mgr.get(req.session_id)
        if not session:
            return {"error": "无效的 session_id，请先调用 /session/new 创建会话"}

        if session.turn_count >= session.max_turns:
            return {"error": f"已达最大轮数 {session.max_turns}，请创建新会话"}

        return StreamingResponse(
            _stream_multiturn(session, req.question, req.max_steps),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── 路由：健康检查 ────────────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "model": MODEL,
            "mode": "multi-turn",
            "active_sessions": len(session_mgr.sessions),
        }

    # ── 路由：托管前端页面 ────────────────────────────────────────────────────
    HTML_PATH = Path(__file__).parent.parent / "multiturn.html"

    @app.get("/")
    async def root():
        if HTML_PATH.exists():
            return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))
        return HTMLResponse("<h2>multiturn.html not found</h2>")

    return app


# ══════════════════════════════════════════════════════════════════════════════
#  入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="多轮对话版 ReAct Financial Agent")
    parser.add_argument("--serve", action="store_true", help="启动 Web 服务")
    parser.add_argument("--host", default="0.0.0.0", help="服务监听地址")
    parser.add_argument("--port", type=int, default=8000, help="服务端口")
    args = parser.parse_args()

    if args.serve:
        import uvicorn
        app = create_app()
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        cli_interactive()
