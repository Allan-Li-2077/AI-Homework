from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


MAX_SKILL_INSTRUCTION_CHARS = 3200
FRONTMATTER_PATTERN = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL)


DEFAULT_CAPABILITY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("web.search", ("search", "find", "look up", "latest", "news", "搜索", "查找", "查询", "最新")),
    ("artifact.docx.create", ("word", ".docx", "document", "report", "作文", "文档", "报告")),
    ("study.flashcard.create", ("flash card", "flashcard", "card", "学习卡片", "记忆卡片", "卡片")),
    ("diagram.create", ("diagram", "flowchart", "sequence", "architecture", "图表", "流程图", "架构图")),
)


@dataclass(frozen=True)
class SkillManifest:
    """Small, model-independent metadata loaded during discovery."""

    id: str
    name: str
    description: str = ""
    manifest_version: int = 1
    enabled: bool = True
    triggers: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    priority: int = 100
    runtime_v2: dict[str, Any] | None = None


@dataclass(frozen=True)
class SkillCard:
    """A lightweight skill record; SKILL.md is intentionally not loaded yet."""

    manifest: SkillManifest
    source: str
    directory: Path
    manifest_path: Path | None
    instruction_path: Path | None

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def name(self) -> str:
        return self.manifest.name


@dataclass(frozen=True)
class LoadedSkill:
    """A task-selected skill with full instructions available for injection."""

    card: SkillCard
    instructions: str

    @property
    def id(self) -> str:
        return self.card.id

    @property
    def name(self) -> str:
        return self.card.name

    @property
    def manifest(self) -> SkillManifest:
        return self.card.manifest

    @property
    def directory(self) -> Path:
        return self.card.directory


class CapabilityDetector:
    """A replaceable prompt-to-capability detector.

    The harness ships with keyword rules so it can run without an LLM. In a
    production agent this object is the seam where a classifier or policy model
    can replace keyword matching without changing the registry or runtime.
    """

    def __init__(self, rules: Iterable[tuple[str, Iterable[str]]] | None = None) -> None:
        source_rules = rules or DEFAULT_CAPABILITY_RULES
        self.rules = tuple((capability, tuple(keywords)) for capability, keywords in source_rules)

    def infer(self, prompt: str) -> tuple[str, ...]:
        normalized = str(prompt or "").lower()
        capabilities: list[str] = []
        for capability, keywords in self.rules:
            if any(keyword.lower() in normalized for keyword in keywords):
                capabilities.append(capability)
        return unique_texts(capabilities)


class SkillRegistry:
    """Discovers, matches, and progressively loads local skills."""

    def __init__(
        self,
        cards: Iterable[SkillCard],
        detector: CapabilityDetector | None = None,
    ) -> None:
        self.cards = {card.id: card for card in cards}
        self.detector = detector or CapabilityDetector()

    @classmethod
    def from_roots(
        cls,
        roots: Iterable[Path | str],
        detector: CapabilityDetector | None = None,
    ) -> "SkillRegistry":
        return cls(load_skill_cards(roots), detector=detector)

    def all_enabled(self) -> tuple[SkillCard, ...]:
        return tuple(
            sorted(
                (card for card in self.cards.values() if card.manifest.enabled),
                key=lambda card: (card.manifest.priority, card.id),
            )
        )

    def get(self, skill_id: str) -> SkillCard | None:
        return self.cards.get(skill_id)

    def resolve_refs(self, skill_ids: Iterable[str]) -> tuple[SkillCard, ...]:
        resolved: list[SkillCard] = []
        seen: set[str] = set()
        for skill_id in skill_ids:
            card = self.get(skill_id)
            if card is None or not card.manifest.enabled or card.id in seen:
                continue
            seen.add(card.id)
            resolved.append(card)
        return tuple(sorted(resolved, key=lambda card: (card.manifest.priority, card.id)))

    def match_prompt(self, prompt: str, already_active: Iterable[str] = ()) -> tuple[SkillCard, ...]:
        normalized_prompt = str(prompt or "").lower()
        active_ids = set(already_active)
        requested_capabilities = set(self.detector.infer(prompt))
        matched: list[SkillCard] = []

        for card in self.all_enabled():
            if card.id in active_ids:
                continue
            manifest = card.manifest
            trigger_hit = any(trigger.lower() in normalized_prompt for trigger in manifest.triggers)
            capability_hit = bool(requested_capabilities.intersection(manifest.capabilities))
            if trigger_hit or capability_hit:
                matched.append(card)

        return tuple(sorted(matched, key=lambda card: (card.manifest.priority, card.id)))

    def load(self, skill_id: str) -> LoadedSkill:
        card = self.cards[skill_id]
        return load_full_skill(card)

    def catalog_context(self, active_skill_ids: Iterable[str] = ()) -> str:
        """Return compact skill summaries suitable for an always-on system prompt."""

        active = set(active_skill_ids)
        lines = [
            "Available installed skills:",
            "Only load full SKILL.md instructions after a user request matches the skill.",
        ]
        for card in self.all_enabled():
            marker = "active" if card.id in active else "available"
            lines.append(format_skill_summary(card, marker=marker))
        return "\n".join(lines)


def load_skill_cards(roots: Iterable[Path | str]) -> tuple[SkillCard, ...]:
    """Load only manifests from skill roots.

    Later roots override earlier roots, matching mini-pi's global -> project
    precedence without carrying over the full application config layer.
    """

    by_id: dict[str, SkillCard] = {}
    for root_value in roots:
        root = Path(root_value)
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            card = load_skill_card(child, source=root.name or "local")
            if card is not None:
                by_id[card.id] = card
    return tuple(sorted(by_id.values(), key=lambda card: (card.manifest.priority, card.id)))


def load_skill_card(path: Path, source: str) -> SkillCard | None:
    manifest_path = path / "skill.json"
    instruction_path = path / "SKILL.md"
    if not manifest_path.is_file() and not instruction_path.is_file():
        return None

    if manifest_path.is_file():
        manifest_data = read_json(manifest_path)
    else:
        # Markdown-only skills need one read at discovery to obtain frontmatter.
        manifest_data = parse_skill_frontmatter(instruction_path.read_text(encoding="utf-8"))

    manifest = manifest_from_data(manifest_data, fallback_id=path.name, fallback_name=path.name)
    return SkillCard(
        manifest=manifest,
        source=source,
        directory=path.resolve(),
        manifest_path=manifest_path.resolve() if manifest_path.is_file() else None,
        instruction_path=instruction_path.resolve() if instruction_path.is_file() else None,
    )


def load_full_skill(card: SkillCard) -> LoadedSkill:
    instructions = ""
    if card.instruction_path and card.instruction_path.is_file():
        instructions = card.instruction_path.read_text(encoding="utf-8")
    return LoadedSkill(card=card, instructions=instructions)


def manifest_from_data(data: dict[str, Any], fallback_id: str, fallback_name: str) -> SkillManifest:
    runtime_v2 = read_dict(data.get("runtimeV2") or data.get("runtime_v2"))
    capabilities = unique_texts([*read_text_list(data.get("capabilities")), *read_text_list(runtime_v2.get("capabilities"))])
    return SkillManifest(
        id=read_text(data.get("id"), fallback_id),
        name=read_text(data.get("name"), fallback_name),
        description=read_text(data.get("description"), ""),
        manifest_version=read_int(data.get("manifestVersion") or data.get("manifest_version"), 1),
        enabled=read_bool(data.get("enabled"), True),
        triggers=tuple(read_text_list(data.get("triggers"))),
        capabilities=tuple(capabilities),
        priority=read_int(data.get("priority"), 100),
        runtime_v2=runtime_v2,
    )


def build_task_skill_message(skills: Iterable[LoadedSkill]) -> str:
    sections: list[str] = []
    for skill in skills:
        sections.append(format_loaded_skill(skill))
    if not sections:
        return ""
    return "Task-matched skills for the current user request:\n" + "\n\n".join(sections)


def format_skill_summary(card: SkillCard, marker: str = "available") -> str:
    manifest = card.manifest
    parts = [f"- {manifest.id} [{marker}]: {manifest.name}"]
    if manifest.description:
        parts.append(manifest.description)
    if manifest.capabilities:
        parts.append(f"capabilities={', '.join(manifest.capabilities)}")
    if manifest.triggers:
        parts.append(f"triggers={', '.join(manifest.triggers)}")
    return "; ".join(parts)


def format_loaded_skill(skill: LoadedSkill) -> str:
    manifest = skill.manifest
    lines = [f"{manifest.id}: {manifest.name}"]
    if manifest.description:
        lines.append(f"Description: {manifest.description}")
    if manifest.capabilities:
        lines.append(f"Capabilities: {', '.join(manifest.capabilities)}")
    if manifest.runtime_v2 and manifest.runtime_v2.get("tools"):
        tool_names = [str(tool.get("name")) for tool in manifest.runtime_v2.get("tools", []) if tool.get("name")]
        lines.append(f"Runtime tools: {', '.join(tool_names)}")
    if skill.instructions:
        lines.append("Instructions:")
        lines.append(compact_text(skill.instructions, MAX_SKILL_INSTRUCTION_CHARS))
    return "\n".join(lines)


def parse_skill_frontmatter(markdown: str) -> dict[str, Any]:
    match = FRONTMATTER_PATTERN.match(str(markdown or ""))
    if not match:
        return {}

    values: dict[str, Any] = {}
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip().strip("\"'")
        if value.startswith("[") and value.endswith("]"):
            values[key.strip()] = [item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]
        else:
            values[key.strip()] = value
    return values


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON manifest: {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Skill manifest must be a JSON object: {path}")
    return data


def read_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def read_text(value: Any, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def read_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list | tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def read_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def unique_texts(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value).strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return tuple(result)


def compact_text(text: str, max_chars: int) -> str:
    stripped = str(text or "").strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[:max_chars].rstrip() + f"\n[truncated: {len(stripped)} chars total]"
