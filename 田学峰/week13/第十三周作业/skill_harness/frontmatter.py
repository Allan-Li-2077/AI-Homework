from __future__ import annotations

from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_frontmatter(path: Path) -> tuple[dict[str, str], int]:
    """只读取 SKILL.md 顶部的 frontmatter。

    提示：frontmatter 就是 Markdown 文件开头两个 --- 中间的那段元信息。
    harness 先读这小段内容，用来判断“哪个 skill 可能适合当前请求”，避免一上来
    把所有 skill 的完整说明都塞进上下文。
    """
    lines: list[str] = []
    char_count = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        first = f.readline()
        char_count += len(first)
        if first.strip() != "---":
            return {}, char_count
        for line in f:
            char_count += len(line)
            if line.strip() == "---":
                break
            lines.append(line.rstrip("\n"))
    return parse_simple_yaml(lines), char_count


def parse_simple_yaml(lines: list[str]) -> dict[str, str]:
    """解析 skill frontmatter 里会用到的一小部分 YAML 写法。

    当前只支持两种最常见格式：
      key: value
      key: >-
        多行折叠文本

    这里没有引入 PyYAML，是为了让示例保持“下载后直接能跑”。
    """
    data: dict[str, str] = {}
    key: str | None = None
    folded: list[str] = []

    def flush() -> None:
        nonlocal key, folded
        if key is not None:
            data[key] = " ".join(part.strip() for part in folded).strip()
        key = None
        folded = []

    for raw in lines:
        if not raw.strip():
            if key is not None:
                folded.append("")
            continue
        if raw.startswith((" ", "\t")) and key is not None:
            folded.append(raw.strip())
            continue
        flush()
        if ":" not in raw:
            continue
        k, value = raw.split(":", 1)
        k = k.strip()
        value = value.strip()
        if value in {">", ">-", "|", "|-"}:
            key = k
            folded = []
        else:
            data[k] = _strip_quotes(value)
    flush()
    return data


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
