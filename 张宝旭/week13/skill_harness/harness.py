from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from week13.skill_harness.registry import LoadedSkill, SkillCard, SkillRegistry, build_task_skill_message
from week13.skill_harness.runtime import execute_runtime_tool, tool_schemas_for_skills


@dataclass(frozen=True)
class PreparedRun:
    """Everything an agent loop needs after progressive skill loading."""

    prompt: str
    catalog_context: str
    active_skills: tuple[LoadedSkill, ...]
    task_skills: tuple[LoadedSkill, ...]
    task_skill_context: str
    tool_schemas: list[dict]
    events: tuple[dict, ...]

    @property
    def loaded_skills(self) -> tuple[LoadedSkill, ...]:
        return (*self.active_skills, *self.task_skills)


class ProgressiveSkillHarness:
    """A minimal harness for progressive skill loading and execution."""

    def __init__(
        self,
        skill_roots: Iterable[Path | str],
        active_skill_ids: Iterable[str] = (),
        registry: SkillRegistry | None = None,
    ) -> None:
        self.skill_roots = tuple(Path(root) for root in skill_roots)
        self.active_skill_ids = tuple(active_skill_ids)
        self.registry = registry or SkillRegistry.from_roots(self.skill_roots)

    def refresh(self) -> None:
        self.registry = SkillRegistry.from_roots(self.skill_roots, detector=self.registry.detector)

    def prepare(self, prompt: str) -> PreparedRun:
        """Load only the skill instructions needed for this one prompt."""

        active_cards = self.registry.resolve_refs(self.active_skill_ids)
        matched_cards = self.registry.match_prompt(
            prompt,
            already_active=tuple(card.id for card in active_cards),
        )

        active_skills = tuple(self.registry.load(card.id) for card in active_cards)
        task_skills = tuple(self.registry.load(card.id) for card in matched_cards)
        loaded_skills = (*active_skills, *task_skills)
        schemas = tool_schemas_for_skills(loaded_skills)
        events = self._events(active_cards=active_cards, matched_cards=matched_cards, schemas=schemas)

        return PreparedRun(
            prompt=prompt,
            catalog_context=self.registry.catalog_context(active_skill_ids=self.active_skill_ids),
            active_skills=active_skills,
            task_skills=task_skills,
            task_skill_context=build_task_skill_message(loaded_skills),
            tool_schemas=schemas,
            events=events,
        )

    def build_messages(self, prompt: str) -> list[dict[str, str]]:
        prepared = self.prepare(prompt)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a base agent with progressively loadable skills.\n"
                    f"{prepared.catalog_context}"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        if prepared.task_skill_context:
            messages.append({"role": "system", "content": prepared.task_skill_context})
        return messages

    def execute_tool(
        self,
        prepared: PreparedRun,
        tool_name: str,
        args: dict,
        cwd: Path | str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> str:
        return execute_runtime_tool(
            tool_name=tool_name,
            args=args,
            cwd=Path(cwd or Path.cwd()),
            skills=prepared.loaded_skills,
            env_overrides=env_overrides or {},
        )

    def _events(
        self,
        active_cards: tuple[SkillCard, ...],
        matched_cards: tuple[SkillCard, ...],
        schemas: list[dict],
    ) -> tuple[dict, ...]:
        return (
            {
                "type": "skill.catalog",
                "count": len(self.registry.all_enabled()),
                "loadedInstructionCount": 0,
            },
            {
                "type": "skill.match",
                "active": [card.id for card in active_cards],
                "matched": [card.id for card in matched_cards],
            },
            {
                "type": "skill.load",
                "loaded": [card.id for card in (*active_cards, *matched_cards)],
            },
            {
                "type": "runtime.tools.expose",
                "tools": [schema["function"]["name"] for schema in schemas],
            },
        )
