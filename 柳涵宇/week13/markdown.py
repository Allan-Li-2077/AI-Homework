from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_FRONTMATTER_DELIM = "---"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def read_frontmatter_only(path: Path) -> tuple[dict[str, Any], int]:
    """Read only the YAML-like front matter block from a SKILL.md file."""
    consumed: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        first = f.readline()
        if not first:
            return {}, 0
        consumed.append(first)
        if first.strip() != _FRONTMATTER_DELIM:
            return {}, len(first.encode("utf-8"))
        for line in f:
            consumed.append(line)
            if line.strip() == _FRONTMATTER_DELIM:
                break
    raw = "".join(consumed)
    text = raw.replace("\r\n", "\n")
    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].strip() == _FRONTMATTER_DELIM:
        block_lines: list[str] = []
        for line in lines[1:]:
            if line.strip() == _FRONTMATTER_DELIM:
                break
            block_lines.append(line)
        return parse_frontmatter_block("\n".join(block_lines)), len(raw.encode("utf-8"))
    return {}, len(raw.encode("utf-8"))


def split_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    text = markdown.replace("\r\n", "\n")
    if not text.startswith(_FRONTMATTER_DELIM):
        return {}, text
    lines = text.splitlines()
    end_index = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FRONTMATTER_DELIM:
            end_index = i
            break
    if end_index is None:
        return {}, text
    block = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :]).lstrip("\n")
    return parse_frontmatter_block(block), body


def parse_frontmatter_block(block: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None
    current_style: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_key, current_style, current_lines
        if current_key is None:
            return
        if current_style in {">", ">-"}:
            value = " ".join(line.strip() for line in current_lines).strip()
        elif current_style in {"|", "|-"}:
            value = "\n".join(current_lines)
        else:
            value = "\n".join(current_lines).strip()
        data[current_key] = _unquote(value)
        current_key = None
        current_style = None
        current_lines = []

    for raw_line in block.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith((" ", "\t")) and current_key is not None:
            current_lines.append(raw_line.strip())
            continue
        flush()
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value in {">", ">-", "|", "|-"}:
            current_key = key
            current_style = value
            current_lines = []
        else:
            data[key] = _coerce_scalar(_unquote(value))
    flush()
    return data


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _coerce_scalar(value: str) -> Any:
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in {"null", "none", "~"}:
        return None
    return value


def parse_headings(markdown_body: str) -> list[str]:
    headings: list[str] = []
    for line in markdown_body.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            headings.append(m.group(2).strip())
    return headings


def extract_skill_relative_paths(markdown: str) -> list[str]:
    """Extract obvious relative resource/script paths mentioned by a SKILL.md."""
    candidates: list[str] = []
    patterns = [
        r"(?:^|[\s`'\"(])((?:references|scripts|data)[/\\][^\s`'\")<>]+)",
        r"\(([^)]*(?:references|scripts|data)[/\\][^)]+)\)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, markdown):
            path = match.group(1).strip().strip("`'\".,;:")
            if not path:
                continue
            path = path.replace("\\", "/")
            if path not in candidates:
                candidates.append(path)
    return candidates


def safe_slug(text: str, default: str = "untitled") -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text.strip().lower()).strip("-")
    return slug or default
