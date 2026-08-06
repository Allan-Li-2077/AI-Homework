"""
skill_optimize: 用户反馈驱动的 Skill 优化模块。

与原有 Nudge 机制的区别：

| 维度 | Nudge（测试集驱动） | skill_optimize（用户反馈驱动） |
|------|-------------------|---------------------------|
| 反馈来源 | 测试集失败样本 | 用户真实体验 |
| 设计成本 | 需要设计测试集 | 无需测试集 |
| 进化触发 | 块结束时批量 | 可实时或批量 |
| 适用场景 | 评估明确的场景 | 主观/创意类生成 |

核心组件：

1. UserFeedbackCollector - 收集用户反馈
2. FeedbackAnalyzer - 分析反馈模式
3. SkillOptimizer - 生成 Skill 改进方案
4. SkillOptimizeManager - 协调整个流程

快速开始：

  from skill_optimize import SkillOptimizeManager, quick_optimize

  # 方式1：管理器模式
  manager = SkillOptimizeManager(skills_dir="skills-origin")
  manager.record_feedback("flashcard", "apple", "['苹果']", "缺少使用场景举例")
  manager.run_optimization("flashcard")

  # 方式2：快速优化
  result = quick_optimize(
      skill_name="flashcard",
      skill_content=skill_md,
      feedback_list=[{"feedback_text": "缺少使用场景"}],
      skill_manager=sm,
  )
"""

from .user_feedback_collector import UserFeedbackCollector, UserFeedback
from .feedback_analyzer import FeedbackAnalyzer, FeedbackPattern
from .skill_optimizer import (
    SkillOptimizer,
    OptimizeAction,
    RuleBasedOptimizer,
    DeveloperOptimizer,
)
from .skill_optimize_manager import SkillOptimizeManager, quick_optimize

__all__ = [
    "UserFeedbackCollector",
    "UserFeedback",
    "FeedbackAnalyzer",
    "FeedbackPattern",
    "SkillOptimizer",
    "SkillOptimizeManager",
    "OptimizeAction",
    "RuleBasedOptimizer",
    "DeveloperOptimizer",
    "quick_optimize",
]
