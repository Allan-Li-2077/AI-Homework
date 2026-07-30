"""
会话持久化模块 — JSON 文件存储

每个会话一个 {session_id}.json，存储在 sessions/ 目录下，结构如下：
{
    "id": "uuid4",
    "created_at": "ISO-8601",
    "history": [
        {"question": "...", "answer": "...", "timestamp": "..."},
        ...
    ]
}

history 保留最近 max_rounds 轮（默认 5）。
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# sessions 目录放在项目根目录下（与 src/ 同级）
_SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
_MAX_ROUNDS = int(os.getenv("SESSION_MAX_ROUNDS", "5"))

# 北京时间
_TZ = timezone(timedelta(hours=8))


def _ensure_dir() -> None:
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(session_id: str) -> Path:
    return _SESSIONS_DIR / f"{session_id}.json"


def _now_iso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


def create_session() -> str:
    """创建新会话，返回 session_id"""
    _ensure_dir()
    sid = uuid.uuid4().hex[:12]  # 12 位 hex，足够短且不易碰撞
    session = {
        "id": sid,
        "created_at": _now_iso(),
        "history": [],
    }
    _save(sid, session)
    logger.info(f"创建会话: {sid}")
    return sid


def get_context(session_id: str) -> list:
    """
    获取会话的最近 N 轮 Q&A 上下文。
    返回格式：[{"question": "...", "answer": "..."}, ...]，最多 _MAX_ROUNDS 对。
    """
    session = _load(session_id)
    if session is None:
        return []
    history = session.get("history", [])
    return history[-_MAX_ROUNDS:]


def add_exchange(session_id: str, question: str, answer: str) -> bool:
    """
    添加一轮 Q&A 到会话历史，自动裁剪保留最近 max_rounds 轮。
    返回 True 表示成功，False 表示会话不存在。
    """
    session = _load(session_id)
    if session is None:
        logger.warning(f"会话不存在: {session_id}")
        return False

    history = session.setdefault("history", [])
    history.append({
        "question": question,
        "answer": answer,
        "timestamp": _now_iso(),
    })

    # 裁剪保留最近 max_rounds 轮
    if len(history) > _MAX_ROUNDS:
        session["history"] = history[-_MAX_ROUNDS:]

    _save(session_id, session)
    return True


def delete_session(session_id: str) -> bool:
    """删除会话文件，返回 True 表示成功"""
    path = _session_path(session_id)
    if path.exists():
        path.unlink()
        logger.info(f"删除会话: {session_id}")
        return True
    return False


def get_session(session_id: str) -> Optional[dict]:
    """获取完整会话数据"""
    return _load(session_id)


def save_session(session_id: str, session: dict) -> bool:
    """覆盖保存会话"""
    return _save(session_id, session)


# ── 内部方法 ──────────────────────────────────────────────────────────────────────

def _load(session_id: str) -> Optional[dict]:
    path = _session_path(session_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"读取会话失败 {session_id}: {e}")
        return None


def _save(session_id: str, session: dict) -> bool:
    _ensure_dir()
    try:
        with open(_session_path(session_id), "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        return True
    except IOError as e:
        logger.error(f"保存会话失败 {session_id}: {e}")
        return False
