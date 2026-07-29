class HarnessError(RuntimeError):
    """Base exception for expected harness failures."""


class SkillNotFoundError(HarnessError):
    """Raised when a requested skill cannot be found."""


class SkillExecutionError(HarnessError):
    """Raised when a skill adapter cannot execute the requested action."""
