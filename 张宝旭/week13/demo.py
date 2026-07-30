from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from week13.skill_harness import ProgressiveSkillHarness


def main() -> None:
    prompt = " ".join(sys.argv[1:]).strip() or "帮我做一张 transformer 的学习卡片"
    harness = ProgressiveSkillHarness([Path(__file__).resolve().parent / "example_skills"])
    prepared = harness.prepare(prompt)

    print("== Progressive Events ==")
    print(json.dumps(prepared.events, ensure_ascii=False, indent=2))
    print()
    print("== Catalog Context ==")
    print(prepared.catalog_context)
    print()
    print("== Task Skill Context ==")
    print(prepared.task_skill_context or "(no task skill matched)")
    print()
    print("== Tool Schemas ==")
    print(json.dumps(prepared.tool_schemas, ensure_ascii=False, indent=2))

    tool_names = {schema["function"]["name"] for schema in prepared.tool_schemas}
    if "make_flashcard" in tool_names:
        print()
        print("== Tool Execution: make_flashcard ==")
        print(harness.execute_tool(prepared, "make_flashcard", {"topic": extract_topic(prompt)}, cwd=ROOT))


def extract_topic(prompt: str) -> str:
    cleaned = prompt.replace("帮我", "").replace("做一张", "").replace("学习卡片", "")
    return " ".join(cleaned.split()).strip() or prompt


if __name__ == "__main__":
    main()
