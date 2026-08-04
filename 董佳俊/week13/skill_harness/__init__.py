"""
skill_harness — Progressive Loading Skill Execution Harness

一个支持渐进式加载（L0 → L1 → L2 → L3）的技能执行引擎。

教学重点：
  1. 渐进式加载 vs 全量加载的性能差异
  2. 技能发现(Phase 0) → 匹配(Phase 1) → 加载(Phase 2) → 注入 → 执行的完整流水线
  3. 未匹配的 skill 零 I/O 开销

主要组件：
  - SkillRegistry: L0 — Frontmatter-only 技能发现
  - SkillLoader:   L1/L2/L3 — 按需加载引擎
  - SkillMatcher:  三层意图匹配
  - SkillHarness:  主流水线（门面类）
  - cli.py:        CLI 演示入口

使用方式：
    harness = SkillHarness()
    harness.startup()
    result = harness.process("画一个架构图")
"""

from .models import SkillMeta, Skill, MatchResult
from .registry import SkillRegistry
from .loader import SkillLoader
from .matcher import SkillMatcher
from .harness import SkillHarness, DEFAULT_SKILLS_DIRS

__all__ = [
    "SkillMeta",
    "Skill",
    "MatchResult",
    "SkillRegistry",
    "SkillLoader",
    "SkillMatcher",
    "SkillHarness",
    "DEFAULT_SKILLS_DIRS",
]

__version__ = "1.0.0"
