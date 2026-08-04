from __future__ import annotations

import json
from pathlib import Path

from week13.skill_harness import ProgressiveSkillHarness


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_skill(root: Path, skill_id: str, triggers: list[str], capabilities: list[str]) -> None:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True)
    write_json(
        skill_dir / "skill.json",
        {
            "id": skill_id,
            "name": skill_id,
            "description": f"{skill_id} summary",
            "triggers": triggers,
            "capabilities": capabilities,
            "runtimeV2": {"capabilities": capabilities, "tools": []},
        },
    )
    (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n\nFULL INSTRUCTIONS FOR {skill_id}", encoding="utf-8")


def test_catalog_does_not_load_full_skill_instructions(tmp_path: Path) -> None:
    write_skill(tmp_path / "skills", "private-skill", ["private"], ["private.capability"])
    harness = ProgressiveSkillHarness([tmp_path / "skills"])

    prepared = harness.prepare("hello world")

    assert "private-skill summary" in prepared.catalog_context
    assert "FULL INSTRUCTIONS FOR private-skill" not in prepared.catalog_context
    assert prepared.task_skill_context == ""
    assert prepared.events[0]["loadedInstructionCount"] == 0


def test_matching_loads_only_relevant_skill_instructions(tmp_path: Path) -> None:
    write_skill(tmp_path / "skills", "alpha", ["alpha"], ["alpha.capability"])
    write_skill(tmp_path / "skills", "beta", ["beta"], ["beta.capability"])
    harness = ProgressiveSkillHarness([tmp_path / "skills"])

    prepared = harness.prepare("please use beta")

    assert [skill.id for skill in prepared.task_skills] == ["beta"]
    assert "FULL INSTRUCTIONS FOR beta" in prepared.task_skill_context
    assert "FULL INSTRUCTIONS FOR alpha" not in prepared.task_skill_context


def test_runtime_tool_is_exposed_and_executed_only_after_match() -> None:
    root = Path(__file__).resolve().parents[1]
    harness = ProgressiveSkillHarness([root / "example_skills"])

    plain = harness.prepare("hello")
    matched = harness.prepare("帮我做一张 Python 的学习卡片")

    assert plain.tool_schemas == []
    assert [schema["function"]["name"] for schema in matched.tool_schemas] == ["make_flashcard"]

    output = harness.execute_tool(matched, "make_flashcard", {"topic": "Python"}, cwd=root)
    assert "Flash Card: Python" in output
