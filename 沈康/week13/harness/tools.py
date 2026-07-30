"""Agent 可调用的工具集：schema 定义 + 实现。

6 个工具：
  - list_dir        列目录，让 agent 发现已有数据文件（满足"已存在则复用"）
  - read_file       读文本文件，不存在返回错误串而非抛异常
  - write_file      写文本文件，自动建父目录
  - run_command     执行命令（跑脚本），cwd 固定为项目根
  - open_in_browser 用默认浏览器打开本地文件
  - finish          标记任务完成并给用户中文总结

所有文件操作均经 :func:`harness.safety.safe_join` 做沙箱校验。
"""
from __future__ import annotations

import logging
import shlex
import subprocess
import sys
import webbrowser
from pathlib import Path

from .safety import safe_join

log = logging.getLogger("harness.tools")

__all__ = [
    "SCHEMAS",
    "list_dir",
    "read_file",
    "write_file",
    "run_command",
    "open_in_browser",
    "finish",
]

# python 解释器别名 → 替换为当前解释器，避免 Windows 下裸 python 不在 PATH
_PYTHON_ALIASES = {"python", "python3", "py"}
# 单次工具输出截断阈值
_MAX_OUTPUT = 8000
# 文件读取截断阈值
_MAX_READ = 50_000
# 命令执行超时（秒）
_CMD_TIMEOUT = 60


# --------------------------------------------------------------------------- #
# 工具实现
# --------------------------------------------------------------------------- #
def list_dir(path: str, *, root: Path) -> str:
    """列出项目根下某目录的内容。"""
    p = safe_join(root, path or ".")
    if p is None:
        return f"ERROR: path out of sandbox: {path!r}"
    if not p.exists():
        return f"ERROR: not found: {path!r}"
    if not p.is_dir():
        return f"ERROR: not a directory: {path!r}"
    rows = []
    for child in sorted(p.iterdir()):
        kind = "dir" if child.is_dir() else "file"
        rows.append(f"{kind}\t{child.name}")
    return "\n".join(rows) if rows else "(empty)"


def read_file(path: str, *, root: Path) -> str:
    """读文本文件。不存在返回错误串（agent 可据此判断文件是否存在）。"""
    p = safe_join(root, path)
    if p is None:
        return f"ERROR: path out of sandbox: {path!r}"
    if not p.is_file():
        return f"ERROR: file not found: {path!r}"
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > _MAX_READ:
        text = text[:_MAX_READ] + "\n...[truncated]"
    return text


def write_file(path: str, content: str, *, root: Path) -> str:
    """写文本文件，自动建父目录。"""
    p = safe_join(root, path)
    if p is None:
        return f"ERROR: path out of sandbox: {path!r}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content or "", encoding="utf-8")
    except OSError as e:
        return f"ERROR: write failed: {type(e).__name__}: {e}"
    return f"OK: wrote {len(content or '')} chars to {path}"


def run_command(command, *, root: Path, timeout: int = _CMD_TIMEOUT) -> str:
    """执行命令，cwd 固定为项目根。

    ``command`` 可为字符串或列表。首位若为 python 别名则替换为 ``sys.executable``。
    使用 ``shell=False`` 防注入；捕获 stdout/stderr 并截断。
    """
    if command is None:
        return "ERROR: empty command"
    if isinstance(command, str):
        # posix=False 保留 Windows 反斜杠路径，不做反斜杠转义
        argv = shlex.split(command, posix=False)
    else:
        argv = [str(a) for a in command]
    if not argv:
        return "ERROR: empty command"

    if argv[0].lower() in _PYTHON_ALIASES:
        argv[0] = sys.executable

    log.info("[audit] run_command argv=%s cwd=%s", argv, root)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(root),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s"
    except FileNotFoundError:
        return f"ERROR: executable not found: {argv[0]}"
    except OSError as e:
        return f"ERROR: {type(e).__name__}: {e}"

    out = proc.stdout or ""
    err = proc.stderr or ""
    result = f"[exit={proc.returncode}]\nstdout:\n{out}"
    if err:
        result += f"\nstderr:\n{err}"
    if len(result) > _MAX_OUTPUT:
        result = result[:_MAX_OUTPUT] + "\n...[truncated]"
    return result


def open_in_browser(path: str, *, root: Path) -> str:
    """用默认浏览器打开项目根下的本地文件。"""
    p = safe_join(root, path)
    if p is None:
        return f"ERROR: path out of sandbox: {path!r}"
    if not p.is_file():
        return f"ERROR: file not found: {path!r}"
    uri = p.resolve().as_uri()  # file:///E:/... 避免裸路径被浏览器当搜索词
    try:
        webbrowser.open(uri)
    except webbrowser.Error as e:
        return f"ERROR: open browser failed: {e}"
    return f"opened: {uri}"


def finish(summary: str) -> str:  # noqa: ARG001
    """标记任务完成。返回值仅作占位，executor 在 dispatch 到 finish 时直接返回 summary。"""
    return "OK"


# --------------------------------------------------------------------------- #
# OpenAI tool-calling schema
# --------------------------------------------------------------------------- #
SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出项目根下某目录的文件和子目录。path 相对项目根，默认 '.'。用于发现已有数据文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对项目根的目录路径，例如 '.skill/flash-card/data'。默认 '.'。",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取项目根下的文本文件内容。文件不存在时返回错误信息，可据此判断文件是否存在。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对项目根的文件路径，例如 '.skill/flash-card/data/crazy.json'。",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "向项目根下写入文本文件，自动创建父目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对项目根的文件路径，例如 '.skill/flash-card/data/word.json'。",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的文本内容（如 JSON 字符串）。",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "执行一条命令，工作目录为项目根。运行 python 脚本时用 'python <脚本路径> <参数>'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": ["string", "array"],
                        "items": {"type": "string"},
                        "description": "要执行的命令，字符串（如 'python .skill/flash-card/scripts/make_flashcard.py .skill/flash-card/data/crazy.json'）或字符串列表。",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_in_browser",
            "description": "用默认浏览器打开项目根下的本地文件（如生成的 HTML）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对项目根的文件路径，例如 'crazy.html'。",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "任务完成后调用，summary 是给用户的中文总结，说明做了什么、产出文件在哪里。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "给用户的中文总结。",
                    }
                },
                "required": ["summary"],
            },
        },
    },
]
