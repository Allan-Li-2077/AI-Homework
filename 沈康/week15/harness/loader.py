"""
Skill 加载器：渐进式加载的核心。

Stage 0（启动）：``SkillRegistry.load_all`` 扫描 ``.skill/*/SKILL.md``，
仅用 PyYAML 解析 frontmatter 得到轻量元数据，不读 body。
Stage 2（按需）：``SkillMeta.load_body`` 懒加载并缓存完整 markdown body。
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("harness.loader")

__all__ = ["SkillMeta", "SkillRegistry"]

# 匹配 ``---\n<yaml>\n---\n<body>``，兼容 LF/CRLF，DOTALL 让 . 跨行
_FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


@dataclass
class SkillMeta:
    """单个 skill 的轻量元数据（frontmatter 字段）+ body 懒加载缓存。"""

    name: str
    description: str
    phase: str | None = None
    kind: str | None = None
    entry: str | None = None
    manual: bool = False
    dir: Path = field(default_factory=Path)
    _body: str | None = field(default=None, repr=False)

    def load_body(self) -> str:
        """懒加载并缓存 SKILL.md 的 markdown body（frontmatter 之后部分）。"""
        if self._body is None:
            text = (self.dir / "SKILL.md").read_text(encoding="utf-8")
            m = _FM_RE.match(text)
            if not m:
                raise ValueError(f"{self.dir / 'SKILL.md'} frontmatter malformed")
            self._body = m.group(2)
            log.info("[stage2] body loaded name=%s chars=%d", self.name, len(self._body))
        return self._body

    def index_line(self) -> str:
        """给 selector 用的单行索引：name [flags]: description。"""
        flags = []
        if self.manual:
            flags.append("manual")
        if self.kind:
            flags.append(f"kind={self.kind}")
        if self.phase:
            flags.append(f"phase={self.phase}")
        fl = f" [{', '.join(flags)}]" if flags else ""
        desc = self.description.strip().replace("\n", " ")
        return f"- {self.name}{fl}: {desc}"


class SkillRegistry:
    """所有 skill 元数据的注册表。"""

    def __init__(self, root: Path):
        self.root = root
        self._skills: dict[str, SkillMeta] = {}

    def load_all(self) -> list[SkillMeta]:
        """扫描 ``.skill/*/SKILL.md``，仅解析 frontmatter（Stage 0）。"""
        self._skills.clear()
        skill_dir = self.root / ".skill"
        if not skill_dir.is_dir():
            log.warning("no .skill dir at %s", skill_dir)
            return []
        found: list[SkillMeta] = []
        for sub in sorted(skill_dir.iterdir()):
            if not sub.is_dir():
                continue
            md = sub / "SKILL.md"
            if not md.is_file():
                continue
            try:
                meta = self._parse_frontmatter(md, sub)
            except Exception as e:  # noqa: BLE001
                log.error("skip %s: %s", sub.name, e)
                continue
            if meta.name in self._skills:
                log.warning("duplicate skill name %s, overwritten by %s", meta.name, sub)
            self._skills[meta.name] = meta
            found.append(meta)
        log.info("[stage0] loaded %d skills: %s", len(found), [m.name for m in found])
        return found

    @staticmethod
    def _parse_frontmatter(md_path: Path, skill_dir: Path) -> SkillMeta:
        text = md_path.read_text(encoding="utf-8")
        m = _FM_RE.match(text)
        if not m:
            raise ValueError("frontmatter not found")
        data = yaml.safe_load(m.group(1))
        if not isinstance(data, dict):
            raise ValueError("frontmatter is not a mapping")
        if "name" not in data or "description" not in data:
            raise ValueError("frontmatter missing name/description")
        return SkillMeta(
            name=str(data["name"]),
            description=str(data["description"]),
            phase=data.get("phase"),
            kind=data.get("kind"),
            entry=data.get("entry"),
            manual=bool(data.get("manual", False)),
            dir=skill_dir,
        )

    def get(self, name: str) -> SkillMeta | None:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return list(self._skills.keys())

    def all(self) -> list[SkillMeta]:
        return list(self._skills.values())
