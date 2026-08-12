"""兼容层：转发到 skill_invoke / lang_worker。"""

from src.sub_agents.translate.lang_worker import SubAgentResult, translate_one
from src.sub_agents.translate.skill_invoke import (
    get_sub_agent,
    invoke_lang_skill,
    list_sub_agents,
    list_sub_skills,
)

__all__ = [
    "SubAgentResult",
    "get_sub_agent",
    "invoke_lang_skill",
    "list_sub_agents",
    "list_sub_skills",
    "translate_one",
]
