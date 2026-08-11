"""
FastAPI HTTP 服务 — 渐进式 Skill Harness 的 SSE 可视化后端

接口：
  POST /chat      SSE 流式对话（含六层加载事件）
  GET  /health    健康检查 + 注册表摘要
  GET  /skills    列出所有 skill（仅元数据）
  GET  /skills/{name}  查看某个 skill 的完整 SKILL.md
  POST /skills/reload  强制重建注册表（新增/修改 SKILL.md 后）
  GET  /memories  查看当前记忆状态
  POST /session/new  开始新会话
  POST /reset    出厂重置
  GET  /          单文件前端 index.html
"""

import os
import sys
import json
import asyncio
import logging
import sqlite3
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from pydantic import BaseModel

from src.progressive_agent import ProgressiveAgent, AgentEvent
from src.skill_registry import get_registry, reload_registry
from src.skill_loader import SkillLoader
from src.skill_executor import SkillExecutor
from src.memory_loader import MemoryLoader
from src.vector_store import VectorStore
from src.fts_store import FTSStore
from src.session_db import SessionDB
from src.llm_config import current_model_info

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── 全局单例 ──────────────────────────────────────────────────────────────────

agent: ProgressiveAgent = None
loader = MemoryLoader()
vs = VectorStore()
fts = FTSStore()
db = SessionDB()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    reload_registry()  # 启动时强制重建一次（新增 skill 后重启生效）
    agent = ProgressiveAgent()
    logger.info(f"渐进式 Harness 启动，已注册 {len(agent.registry)} 个 skill")
    yield
    if agent and agent.session_id:
        db.close_session(agent.session_id)


app = FastAPI(title="Progressive Skill Harness", lifespan=lifespan)


# ── Pydantic 模型 ──────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: int | None = None


class FlushRequest(BaseModel):
    session_id: int | None = None


# ── SSE 工具 ──────────────────────────────────────────────────────────────────

def _sse(event: dict) -> str:
    payload = json.dumps(event, ensure_ascii=False)
    return f"data: {payload}\n\n"


# ── /chat ──────────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    sid = req.session_id or agent.session_id

    async def stream() -> AsyncIterator[str]:
        try:
            for event in agent.handle(req.message):
                yield _sse(event.to_dict())
                await asyncio.sleep(0)
        except Exception as e:
            logger.exception("chat 处理失败")
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ── /health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    info = current_model_info()
    reg = agent.registry if agent else get_registry()
    return {
        "status": "ok",
        "session_id": agent.session_id if agent else None,
        "skill_count": len(reg),
        "registry_summary": reg.summary(),
        "fts_available": fts.available,
        "memory_entries": loader.get_memory_entry_count(),
        "faiss_entries": vs.total_entries,
        "model": info,
    }


# ── /skills ────────────────────────────────────────────────────────────────────

@app.get("/skills")
async def list_skills():
    reg = agent.registry if agent else get_registry()
    return [
        {
            "name": m.name,
            "version": m.version,
            "description": m.description,
            "keywords": m.keywords,
            "triggers": m.triggers,
            "execution": m.execution,
            "parameters": [
                {"name": p.name, "type": p.type, "required": p.required, "description": p.description}
                for p in m.parameters
            ],
            "body_chars": m.body_chars,
            "frontmatter_chars": m.frontmatter_chars,
            "enabled": m.enabled,
        }
        for m in reg.items()
    ]


@app.get("/skills/{name}")
async def get_skill(name: str):
    reg = agent.registry if agent else get_registry()
    meta = reg.get(name)
    if not meta:
        raise HTTPException(404, f"Skill '{name}' 不存在")
    # 读完整 SKILL.md
    text = Path(meta.source_path).read_text(encoding="utf-8")
    return {
        "meta": {
            "name": meta.name,
            "version": meta.version,
            "description": meta.description,
            "keywords": meta.keywords,
            "execution": meta.execution,
            "parameters": [
                {"name": p.name, "type": p.type, "required": p.required, "description": p.description}
                for p in meta.parameters
            ],
        },
        "raw_markdown": text,
    }


@app.post("/skills/reload")
async def reload_skills():
    reg = reload_registry()
    return {"reloaded": True, "skill_count": len(reg), "summary": reg.summary()}


# ── /memories ──────────────────────────────────────────────────────────────────

@app.get("/memories")
async def get_memories():
    mem_dir = loader.memory_dir

    def read_md(name):
        p = mem_dir / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    return {
        "user_md":      read_md("USER.md"),
        "memory_md":    read_md("MEMORY.md"),
        "soul_md":      read_md("SOUL.md"),
        "agents_md":    read_md("AGENTS.md"),
        "entry_count":  loader.get_memory_entry_count(),
        "faiss_total":  vs.total_entries,
        "fts_total":    fts.total_entries,
        "fts_available": fts.available,
        "recent_sessions": db.get_recent_sessions(5),
    }


# ── /session/new ───────────────────────────────────────────────────────────────

@app.post("/session/new")
async def new_session():
    sid = agent.new_session()
    return {"session_id": sid}


# ── /reset ─────────────────────────────────────────────────────────────────────

@app.post("/reset")
async def factory_reset():
    """回到出厂初始态"""
    global agent
    # 重置 memory/
    mem_dir = loader.memory_dir
    project_root = mem_dir.parent
    backups_dir = project_root / "backups" / "initial" / "memory"
    initial_map = {
        "USER.md":   "# USER.md\n\n## 基本信息\n- 姓名：（尚未告知）\n## 用过的 Skills\n（暂无）\n",
        "MEMORY.md": "# MEMORY.md\n\n<!-- MEMORY_ENTRIES_START -->\n<!-- MEMORY_ENTRIES_END -->\n",
    }
    for name, content in initial_map.items():
        (mem_dir / name).write_text(content, encoding="utf-8")
    for name in ("SOUL.md", "AGENTS.md"):
        src = backups_dir / name
        if src.exists():
            (mem_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    # 清空 FAISS
    for f in ("memory.faiss", "memory_meta.pkl"):
        p = vs.index_dir / f
        if p.exists():
            p.unlink()
    vs.index = None
    vs.metadata = []

    # 清空 SQLite
    conn = sqlite3.connect(db.db_path)
    conn.executescript("DELETE FROM messages; DELETE FROM sessions;")
    try:
        conn.execute("DELETE FROM memory_fts")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
    db._init_db()

    # 重启 agent
    agent.new_session()
    reload_registry()
    return {"status": "ok", "session_id": agent.session_id}


# ── 静态文件 ──────────────────────────────────────────────────────────────────

INDEX_HTML = Path(__file__).parent.parent / "index.html"


@app.get("/")
async def root():
    return FileResponse(INDEX_HTML)