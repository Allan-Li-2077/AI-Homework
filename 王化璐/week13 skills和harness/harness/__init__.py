"""
渐进式加载执行Skills的Harness系统

核心模块:
- SkillRegistry: 发现与注册Skills（轻量级扫描SKILL.md frontmatter）
- SkillLoader: 渐进式加载Skill完整内容
- SkillMatcher: 意图匹配（正则初筛 + 可选LLM判断）
- SkillExecutor: Skill流程执行引擎
- Harness: 编排器，串联以上组件
"""

from .skill_registry import SkillRegistry, SkillMeta
from .skill_loader import SkillLoader, SkillContent
from .skill_matcher import SkillMatcher, MatchResult
from .skill_executor import SkillExecutor, ExecutionResult
from .harness import Harness, HarnessEvent

__all__ = [
    "SkillRegistry", "SkillMeta",
    "SkillLoader", "SkillContent",
    "SkillMatcher", "MatchResult",
    "SkillExecutor", "ExecutionResult",
    "Harness", "HarnessEvent",
]
