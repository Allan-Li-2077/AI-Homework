"""Skill 数据结构与懒加载机制"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    """单个 Skill，包含懒加载的完整内容"""

    name: str                          # skill 唯一标识名
    description: str                   # 一句话描述（用于匹配用户问题）
    path: Path                         # SKILL.md 所在目录

    _full_content: dict | None = field(default=None, repr=False)
    _functions_cache: list[dict] | None = field(default=None, repr=False)

    # --- 懒加载：只有在需要时才读取完整 SKILL.md ---
    def load(self) -> dict[str, Any]:
        """加载完整的 skill 内容（只执行一次）"""
        if self._full_content is None:
            self._full_content = self._read_skill_md()
        return self._full_content

    def _read_skill_md(self) -> dict[str, Any]:
        """解析 SKILL.md，提取 frontmatter + 所有 heading + 代码块"""
        skill_md = self.path / "SKILL.md"
        if not skill_md.exists():
            return {"raw": "", "functions": []}

        raw = skill_md.read_text(encoding="utf-8")
        return parse_skill_md(raw)

    @property
    def is_loaded(self) -> bool:
        return self._full_content is not None


def parse_skill_md(raw: str) -> dict[str, Any]:
    """解析 SKILL.md 内容，提取 frontmatter、文档结构、代码块"""
    lines = raw.splitlines()
    result = {
        "raw": raw,
        "frontmatter": {},
        "headings": [],
        "code_blocks": [],
        "functions": [],        # 从文档中提取的 function call 定义
    }

    # 1. 解析 frontmatter (YAML)
    if lines and lines[0].strip() == "---":
        fence_end = -1
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                fence_end = i
                break
        if fence_end > 1:
            import yaml
            try:
                result["frontmatter"] = yaml.safe_load("\n".join(lines[1:fence_end]))
            except Exception:
                pass

    # 2. 提取所有 heading（## 开头的行）
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.+)", line)
        if m:
            result["headings"].append({"level": len(m.group(1)), "text": m.group(2).strip()})

    # 3. 提取所有 ``` 语言块
    in_block = False
    block_lang = ""
    block_lines = []
    for line in lines:
        if line.startswith("```") and not in_block:
            in_block = True
            block_lang = line[3:].strip()
            block_lines = []
        elif line.startswith("```") and in_block:
            result["code_blocks"].append({
                "language": block_lang,
                "content": "\n".join(block_lines),
            })
            in_block = False
        elif in_block:
            block_lines.append(line)

    return result


def _ensure_type_field(fn: dict) -> None:
    """OpenAI API 要求每个 tool 必须有 type='function' 字段，补上它"""
    if "type" not in fn:
        fn["type"] = "function"


def extract_functions_from_skill(skill: Skill) -> list[dict]:
    """
    从 skill 内容中解析出 function_call 定义（带缓存）。
    约定：SKILL.md 中用 ```json 代码块定义 function schema。
    """
    if skill._functions_cache is not None:
        return skill._functions_cache

    content = skill.load()
    raw = content.get("raw", "")
    functions = []
    in_block = False
    block_lines = []

    for line in raw.splitlines():
        if line.startswith("```json") and not in_block:
            in_block = True
            block_lines = []
        elif line.startswith("```") and in_block:
            try:
                import json
                candidate = json.loads("\n".join(block_lines))
                if isinstance(candidate, dict) and "name" in candidate:
                    _ensure_type_field(candidate)
                    functions.append(candidate)
                elif isinstance(candidate, list):
                    for f in candidate:
                        if isinstance(f, dict) and "name" in f:
                            _ensure_type_field(f)
                            functions.append(f)
            except Exception:
                pass
            in_block = False
        elif in_block:
            block_lines.append(line)

    skill._functions_cache = functions
    return functions
