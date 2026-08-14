"""翻译 Sub-Agent 系统：主 Skill 分发，独立子 Skill 执行。"""

from src.sub_agents.translate.config import (
    get_parallel_enabled,
    set_parallel_enabled,
)
from src.sub_agents.translate.main_agent import TranslateMainAgent
from src.sub_agents.translate.parse import (
    CODE_TO_SKILL,
    detect_targets,
    has_translate_intent,
    parse_query,
)
from src.sub_agents.translate.skill_invoke import invoke_lang_skill, list_sub_skills

__all__ = [
    "CODE_TO_SKILL",
    "TranslateMainAgent",
    "detect_targets",
    "get_parallel_enabled",
    "has_translate_intent",
    "invoke_lang_skill",
    "list_sub_skills",
    "parse_query",
    "set_parallel_enabled",
]
