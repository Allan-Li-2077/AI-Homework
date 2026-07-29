"""Progressive skill loading harness.

This package discovers SKILL.md based skills from a local skills directory, routes
requests using metadata only, then loads the selected skill and optional resources
just-in-time.
"""

from .models import SkillMeta, LoadedSkill, LoadedResource, TraceEvent, RunResult
from .registry import SkillRegistry
from .router import SkillRouter
from .session import ProgressiveSkillHarness
from .executor import SkillExecutor

__all__ = [
    "SkillMeta",
    "LoadedSkill",
    "LoadedResource",
    "TraceEvent",
    "RunResult",
    "SkillRegistry",
    "SkillRouter",
    "ProgressiveSkillHarness",
    "SkillExecutor",
]
