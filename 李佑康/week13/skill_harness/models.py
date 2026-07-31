from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    keywords: tuple[str, ...]
    executor: str
    entrypoint: str | None
    root: Path


@dataclass(frozen=True)
class Skill:
    metadata: SkillMetadata
    instructions: str


@dataclass(frozen=True)
class HarnessEvent:
    stage: str
    skill: str | None
    detail: str


@dataclass
class HarnessResult:
    skill: str
    output: Any
    events: list[HarnessEvent] = field(default_factory=list)
