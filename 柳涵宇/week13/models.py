from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillMeta:
    """Small metadata object loaded from SKILL.md front matter only."""

    name: str
    description: str
    path: Path
    skill_dir: Path
    version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    frontmatter_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "path": str(self.path),
            "skill_dir": str(self.skill_dir),
            "frontmatter_bytes": self.frontmatter_bytes,
            "metadata": dict(self.metadata),
        }


@dataclass
class LoadedSkill:
    """A selected skill after its full SKILL.md has been loaded."""

    meta: SkillMeta
    markdown: str
    body: str
    headings: list[str] = field(default_factory=list)

    def to_dict(self, include_markdown: bool = False) -> dict[str, Any]:
        data = {
            "meta": self.meta.to_dict(),
            "body_chars": len(self.body),
            "headings": list(self.headings),
        }
        if include_markdown:
            data["markdown"] = self.markdown
        return data


@dataclass
class LoadedResource:
    """A lazily loaded resource referenced by a selected skill."""

    path: Path
    relative_path: str
    content: str

    def to_dict(self, include_content: bool = False) -> dict[str, Any]:
        data = {
            "path": str(self.path),
            "relative_path": self.relative_path,
            "chars": len(self.content),
        }
        if include_content:
            data["content"] = self.content
        return data


@dataclass
class TraceEvent:
    """One progressive-loading event."""

    phase: str
    detail: str
    path: str | None = None
    bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {"phase": self.phase, "detail": self.detail}
        if self.path is not None:
            data["path"] = self.path
        if self.bytes is not None:
            data["bytes"] = self.bytes
        return data


@dataclass
class RunResult:
    """Result returned by a skill execution adapter."""

    skill: str
    returncode: int
    command: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    outputs: list[Path] = field(default_factory=list)
    loaded_resources: list[LoadedResource] = field(default_factory=list)
    trace: list[TraceEvent] = field(default_factory=list)

    def to_dict(self, include_resources: bool = False) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "returncode": self.returncode,
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "outputs": [str(p) for p in self.outputs],
            "loaded_resources": [r.to_dict(include_content=include_resources) for r in self.loaded_resources],
            "trace": [e.to_dict() for e in self.trace],
        }
