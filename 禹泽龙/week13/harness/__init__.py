"""
Harness —— 渐进式加载 Skills 的 AI Agent 框架

核心设计：
1. 启动时只扫描 skill 的 name + description（轻量）
2. 用户提问时匹配并加载相关 skill 的完整内容
3. Skill 中定义 function call，大模型决定调用它完成任务

目录结构约定：
skills/
  <skill-name>/
    SKILL.md          # 必须：包含 name/description frontmatter + 文档
    scripts/          # 可选：执行具体逻辑的脚本
      make_flashcard.py
    data/             # 可选：数据文件
"""

from .skill import Skill, parse_skill_md, extract_functions_from_skill
from .registry import SkillRegistry
from .agent import (
    HarnessAgent, AgentConfig,
    get_chat_client, get_provider, PROVIDERS,
)

__all__ = [
    "Skill",
    "parse_skill_md",
    "extract_functions_from_skill",
    "SkillRegistry",
    "HarnessAgent",
    "AgentConfig",
    "get_chat_client",
    "get_provider",
    "PROVIDERS",
]
