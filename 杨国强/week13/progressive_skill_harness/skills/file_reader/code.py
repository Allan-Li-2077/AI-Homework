"""
file_reader skill 的 code.py — 由 SkillExecutor 在 sandbox 中执行

可用 API（在 sandbox 中注入）：
  - params: dict   — SkillLoader 解析后的参数
  - context: dict  — 调用上下文（含 user_query, memory_snippets 等）
  - read_file(path, limit=4000): str
  - log(msg): None — 广播日志到前端
  - shell(cmd, timeout=10): dict — 白名单命令执行
  - emit(event_type, data): None — 广播事件
"""

import os
from pathlib import Path

# ── 白名单：只允许读取文本类文件 ──────────────────────────────────────────────
TEXT_EXTENSIONS = {".txt", ".md", ".py", ".json", ".csv", ".log", ".yaml", ".yml",
                   ".toml", ".ini", ".conf", ".sh", ".bat", ".html", ".css", ".js",
                   ".ts", ".tsx", ".jsx", ".sql", ".xml"}

MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MB
ALLOWED_ROOTS = [Path.cwd(), Path.cwd().parent]  # 仅允许当前目录及其父目录


def _validate_path(path_str: str) -> Path:
    """校验路径在白名单内、扩展名合法、文件大小可接受"""
    p = Path(path_str).resolve()
    # 必须存在于某个允许根目录下
    if not any(str(p).startswith(str(root)) for root in ALLOWED_ROOTS):
        raise PermissionError(f"路径不在允许范围内：{p}")
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{p}")
    if not p.is_file():
        raise IsADirectoryError(f"是目录而非文件：{p}")
    if p.suffix.lower() not in TEXT_EXTENSIONS:
        raise ValueError(f"扩展名 {p.suffix} 不在白名单（仅允许文本类）")
    if p.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"文件过大（>{MAX_FILE_BYTES} bytes）")
    return p


def main(params: dict) -> dict:
    path_str = params.get("path", "").strip()
    question = params.get("question", "").strip()
    max_chars = int(params.get("max_chars") or 4000)

    if not path_str:
        return {"text": "❌ 缺少必填参数 `path`", "metadata": {}, "preview": ""}

    log(f"读取文件：{path_str}")

    try:
        p = _validate_path(path_str)
    except Exception as e:
        return {"text": f"❌ 校验失败：{e}", "metadata": {"path": path_str}, "preview": ""}

    try:
        content = read_file(str(p), limit=max_chars)
    except Exception as e:
        return {"text": f"❌ 读取失败：{e}", "metadata": {"path": str(p)}, "preview": ""}

    truncated = len(content) >= max_chars
    metadata = {
        "path": str(p),
        "size_bytes": p.stat().st_size,
        "encoding": "utf-8",
        "lines": content.count("\n") + 1,
        "truncated": truncated,
    }

    if not question:
        # 没有具体问题 → 返回预览 + 元信息
        preview = content[:1500] + ("\n\n...[截断]..." if truncated else "")
        text = (
            f"📄 **{p.name}**\n"
            f"- 路径：`{p}`\n"
            f"- 大小：{metadata['size_bytes']:,} bytes\n"
            f"- 行数：{metadata['lines']}\n"
            f"- 截断：{'是' if truncated else '否'}\n\n"
            f"```\n{preview}\n```"
        )
        return {"text": text, "metadata": metadata, "preview": preview}

    # 有问题 → 这里只负责把"文件内容 + 问题"组合好交给上层 LLM 回答
    # （真正的 LLM 调用由 SkillExecutor 的 prompt fallback 路径处理 — 但本 skill 是 code 类型，
    # 所以由 agent 主循环根据 result.raw_output 决定是否再调一次 LLM。
    # 这里为简化，返回 content 全文，由 Agent 在结果里拼给最终 LLM 处理）
    text = (
        f"📄 已读取 **{p.name}**（{metadata['lines']} 行，{metadata['size_bytes']:,} bytes）\n"
        f"用户问题：{question}\n\n"
        f"【文件内容预览】\n```\n{content}\n```"
    )
    return {"text": text, "metadata": metadata, "preview": content, "needs_llm": True}