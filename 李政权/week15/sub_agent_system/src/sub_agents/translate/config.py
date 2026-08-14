"""
翻译子 Skill 并行开关。

优先级：
  1. 运行时内存（API set_parallel_enabled）
  2. 持久化文件 data/translate_mode.json
  3. 环境变量 TRANSLATE_PARALLEL（1/true/on → 并行；0/false/off → 串行）
  4. 默认并行
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _PROJECT_ROOT / "data" / "translate_mode.json"

_runtime_parallel: Optional[bool] = None


def _env_parallel() -> bool:
    raw = os.getenv("TRANSLATE_PARALLEL", "1").strip().lower()
    return raw in ("1", "true", "yes", "on", "parallel")


def _read_file() -> Optional[bool]:
    try:
        if not _CONFIG_PATH.exists():
            return None
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        if "parallel" in data:
            return bool(data["parallel"])
    except Exception:
        return None
    return None


def _write_file(enabled: bool) -> None:
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(
            json.dumps(
                {
                    "parallel": bool(enabled),
                    "mode": "parallel" if enabled else "serial",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def get_parallel_enabled() -> bool:
    if _runtime_parallel is not None:
        return _runtime_parallel
    saved = _read_file()
    if saved is not None:
        return saved
    return _env_parallel()


def set_parallel_enabled(enabled: bool) -> bool:
    global _runtime_parallel
    _runtime_parallel = bool(enabled)
    _write_file(_runtime_parallel)
    return _runtime_parallel


def describe_mode() -> dict:
    file_val = _read_file()
    return {
        "parallel": get_parallel_enabled(),
        "mode": "parallel" if get_parallel_enabled() else "serial",
        "env_TRANSLATE_PARALLEL": os.getenv("TRANSLATE_PARALLEL", "1"),
        "runtime_override": _runtime_parallel,
        "file_parallel": file_val,
        "config_path": str(_CONFIG_PATH),
    }
