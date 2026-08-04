from __future__ import annotations

"""skill_harness: 渐进式加载并执行 Skills 的 harness。"""

from .cli import DEFAULT_SKILLS_DIR, list_skills, main, print_matches
from .frontmatter import parse_simple_yaml, read_frontmatter, read_text
from .loader import ProgressiveLoader
from .matcher import SkillMatcher, tokenize
from .models import (
    ExecutionContext,
    LoadedReference,
    LoadedSkill,
    MatchResult,
    RunnerResult,
    SkillMetadata,
    estimate_tokens,
)
from .registry import SkillRegistry
from .runners import DiagramRunner, FlashCardRunner, RunnerRegistry, SkillRunner

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_SKILLS_DIR",
    "DiagramRunner",
    "ExecutionContext",
    "FlashCardRunner",
    "LoadedReference",
    "LoadedSkill",
    "MatchResult",
    "ProgressiveLoader",
    "RunnerRegistry",
    "RunnerResult",
    "SkillMatcher",
    "SkillMetadata",
    "SkillRegistry",
    "SkillRunner",
    "estimate_tokens",
    "list_skills",
    "main",
    "parse_simple_yaml",
    "print_matches",
    "read_frontmatter",
    "read_text",
    "tokenize",
]
