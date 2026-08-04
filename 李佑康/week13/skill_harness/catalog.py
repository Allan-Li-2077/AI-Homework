from __future__ import annotations

import json
import re
from pathlib import Path

from .models import HarnessEvent, Skill, SkillMetadata

_FRONT_MATTER_LIMIT = 16 * 1024


def _parse_scalar(value: str):
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        return json.loads(value.replace("'", '"'))
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def _parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md 必须以 YAML front matter 开头")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("SKILL.md 缺少 front matter 结束标记")
    data: dict[str, object] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"不支持的 front matter 行: {line}")
        key, value = line.split(":", 1)
        data[key.strip()] = _parse_scalar(value)
    return data, text[end + 5 :].strip()


class SkillCatalog:
    """只扫描元数据；完整指令在真正选中 Skill 后才读取。"""

    def __init__(self, skills_dir: Path, events: list[HarnessEvent]):
        self.skills_dir = skills_dir.resolve()
        self.events = events
        self._items: dict[str, SkillMetadata] = {}

    def discover(self) -> list[SkillMetadata]:
        self._items.clear()
        for skill_file in sorted(self.skills_dir.glob("*/SKILL.md")):
            with skill_file.open("r", encoding="utf-8") as handle:
                head = handle.read(_FRONT_MATTER_LIMIT)
            data, _ = _parse_front_matter(head)
            required = {"name", "description", "keywords"}
            missing = required - data.keys()
            if missing:
                raise ValueError(f"{skill_file}: 缺少字段 {sorted(missing)}")
            executor = str(data.get("executor", "python"))
            entrypoint = data.get("entrypoint")
            if executor not in {"python", "llm"}:
                raise ValueError(f"{skill_file}: executor 只支持 python 或 llm")
            if executor == "python" and not entrypoint:
                raise ValueError(f"{skill_file}: Python Skill 必须提供 entrypoint")
            metadata = SkillMetadata(
                name=str(data["name"]),
                description=str(data["description"]),
                keywords=tuple(str(x).lower() for x in data["keywords"]),
                executor=executor,
                entrypoint=str(entrypoint) if entrypoint else None,
                root=skill_file.parent.resolve(),
            )
            if metadata.name in self._items:
                raise ValueError(f"Skill 名称重复: {metadata.name}")
            self._items[metadata.name] = metadata
            self.events.append(
                HarnessEvent("discover", metadata.name, "仅加载名称、描述和路由关键词")
            )
        return list(self._items.values())

    def choose(self, request: str, requested_skill: str | None = None) -> SkillMetadata:
        if not self._items:
            self.discover()
        if requested_skill:
            try:
                chosen = self._items[requested_skill]
            except KeyError as exc:
                raise LookupError(f"未找到 Skill: {requested_skill}") from exc
        else:
            lowered = request.lower()
            tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", lowered))

            def score(item: SkillMetadata) -> int:
                keyword_score = sum(
                    3 for keyword in item.keywords if keyword in lowered or keyword in tokens
                )
                description_score = sum(
                    1 for token in tokens if len(token) > 1 and token in item.description.lower()
                )
                return keyword_score + description_score

            ranked = sorted(self._items.values(), key=lambda item: (-score(item), item.name))
            if not ranked or score(ranked[0]) == 0:
                names = "、".join(sorted(self._items))
                raise LookupError(f"没有匹配的 Skill；可用 Skill: {names}")
            chosen = ranked[0]
        self.events.append(HarnessEvent("route", chosen.name, "根据请求选择 Skill"))
        return chosen

    def load(self, metadata: SkillMetadata) -> Skill:
        skill_file = metadata.root / "SKILL.md"
        text = skill_file.read_text(encoding="utf-8")
        _, instructions = _parse_front_matter(text)
        self.events.append(
            HarnessEvent("load_instructions", metadata.name, "加载完整 SKILL.md 指令")
        )
        return Skill(metadata=metadata, instructions=instructions)
