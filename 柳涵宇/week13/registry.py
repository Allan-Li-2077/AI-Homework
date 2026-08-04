from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from .errors import SkillNotFoundError
from .markdown import read_frontmatter_only, read_text, split_frontmatter, parse_headings
from .models import LoadedSkill, SkillMeta, TraceEvent


class SkillRegistry:
    """Discover and load local SKILL.md packages progressively."""

    def __init__(self, skill_dirs: Iterable[str | Path] | None = None, *, cwd: str | Path | None = None):
        self.cwd = Path(cwd or Path.cwd()).resolve()
        self.skill_dirs = [Path(p).resolve() for p in (skill_dirs or self._default_skill_dirs())]
        self._metas: dict[str, SkillMeta] | None = None
        self._loaded: dict[str, LoadedSkill] = {}
        self.trace: list[TraceEvent] = []

    def _default_skill_dirs(self) -> list[Path]:
        candidates = [self.cwd / "skills", self.cwd / ".cursor" / "skills"]
        existing = [p for p in candidates if p.exists()]
        return existing or [self.cwd / "skills"]

    def discover(self, *, refresh: bool = False) -> list[SkillMeta]:
        if self._metas is not None and not refresh:
            return sorted(self._metas.values(), key=lambda m: m.name)

        metas: dict[str, SkillMeta] = {}
        for root in self.skill_dirs:
            if not root.exists():
                self.trace.append(TraceEvent("discover", "skip missing skills dir", str(root)))
                continue
            for skill_file in self._iter_skill_files(root):
                metadata, consumed = read_frontmatter_only(skill_file)
                name = str(metadata.get("name") or skill_file.parent.name)
                description = str(metadata.get("description") or "")
                version = metadata.get("version")
                meta = SkillMeta(
                    name=name,
                    description=description,
                    version=str(version) if version is not None else None,
                    path=skill_file,
                    skill_dir=skill_file.parent,
                    metadata=metadata,
                    frontmatter_bytes=consumed,
                )
                if name in metas:
                    self.trace.append(
                        TraceEvent(
                            "discover",
                            f"skipped duplicate skill {name}",
                            str(skill_file),
                            consumed,
                        )
                    )
                    continue
                metas[name] = meta
                self.trace.append(
                    TraceEvent(
                        "discover",
                        f"loaded front matter for {name}",
                        str(skill_file),
                        consumed,
                    )
                )
        self._metas = metas
        return sorted(metas.values(), key=lambda m: m.name)

    def _iter_skill_files(self, root: Path) -> Iterable[Path]:
        seen: set[Path] = set()
        for child in sorted(root.iterdir()):
            if child.name in {"node_modules", ".git", "__pycache__"}:
                continue
            skill_file = child / "SKILL.md"
            if skill_file.exists():
                resolved = skill_file.resolve()
                seen.add(resolved)
                yield resolved
        for skill_file in sorted(root.rglob("SKILL.md")):
            if any(part in {"node_modules", ".git", "__pycache__"} for part in skill_file.parts):
                continue
            resolved = skill_file.resolve()
            if resolved in seen:
                continue
            yield resolved

    def get_meta(self, name: str) -> SkillMeta:
        metas = {m.name: m for m in self.discover()}
        if name in metas:
            return metas[name]
        lowered = name.lower()
        for meta in metas.values():
            if meta.name.lower() == lowered or meta.skill_dir.name.lower() == lowered:
                return meta
        raise SkillNotFoundError(f"Skill not found: {name}")

    def load_skill(self, name: str) -> LoadedSkill:
        meta = self.get_meta(name)
        if meta.name in self._loaded:
            return self._loaded[meta.name]
        markdown = read_text(meta.path)
        _, body = split_frontmatter(markdown)
        loaded = LoadedSkill(meta=meta, markdown=markdown, body=body, headings=parse_headings(body))
        self._loaded[meta.name] = loaded
        self.trace.append(
            TraceEvent("load_skill", f"loaded full SKILL.md for {meta.name}", str(meta.path), len(markdown.encode("utf-8")))
        )
        return loaded
