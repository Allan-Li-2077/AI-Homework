"""
Skill 注册表 — 扫描目录、解析 SKILL.md frontmatter、惰性加载完整内容

核心设计：
  - 触发层（Always-loaded）：只存 name + description（<50 tokens/skill）
  - 按需层（On Demand）：调用 load_full() 时才读取完整 SKILL.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillIndex:
    """触发层索引 — 只保留匹配用的轻量信息"""
    name: str
    description: str
    path: Path = field(repr=False)
    version: str = ""
    _full_content: str | None = field(default=None, repr=False)

    @property
    def trigger_hint(self) -> str:
        """从 description 提取触发关键词提示（前 200 字符）"""
        return self.description[:200]

    def load_full(self) -> str:
        """按需加载完整 SKILL.md 内容"""
        if self._full_content is None:
            self._full_content = self.path.read_text(encoding="utf-8")
        return self._full_content

    def unload(self):
        """释放完整内容（上下文清理）"""
        self._full_content = None

    @property
    def is_loaded(self) -> bool:
        return self._full_content is not None

    @property
    def full_token_estimate(self) -> int:
        """粗略估算完整内容的 token 数（中文约 1.5 字符/token）"""
        if self._full_content:
            return len(self._full_content) // 2
        return 0


def parse_frontmatter(text: str) -> dict:
    """解析 YAML frontmatter（--- 分隔块）"""
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    raw = match.group(1)
    result = {}
    # 简单 YAML 解析（不引入 pyyaml 依赖，只处理 key: value 格式）
    current_key = None
    multiline_value = []
    for line in raw.split("\n"):
        # 处理多行值（>- 或 |）
        if current_key and (line.startswith("  ") or line.startswith("\t")):
            multiline_value.append(line.strip())
            continue
        if current_key and multiline_value:
            result[current_key] = " ".join(multiline_value)
            current_key = None
            multiline_value = []

        # key: value
        m = re.match(r"^(\w[\w-]*):\s*(.*)", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            # 处理 >- 折叠标记
            if val in (">-", "|", "|-", ">"):
                current_key = key
                multiline_value = []
            else:
                result[key] = val

    if current_key and multiline_value:
        result[current_key] = " ".join(multiline_value)

    return result


def scan_skills(skills_dir: str | Path) -> list[SkillIndex]:
    """扫描 skills 目录，返回触发层索引列表"""
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        return []

    indices = []
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if not fm.get("name"):
            continue
        indices.append(SkillIndex(
            name=fm["name"],
            description=fm.get("description", ""),
            path=skill_md,
            version=fm.get("version", ""),
        ))
    return indices
