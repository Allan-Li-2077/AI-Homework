"""Local Skill discovery with progressive instruction loading."""

from dataclasses import dataclass
from pathlib import Path

import yaml


WORK_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = WORK_ROOT / "skills"


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    version: str | None
    base_dir: Path
    skill_md_path: Path

    def public_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
        }


class SkillRegistry:
    def __init__(self, skills_root: Path = SKILLS_ROOT):
        self.skills_root = skills_root.resolve()
        self._skills: dict[str, SkillMetadata] = {}
        self.discover()

    def discover(self) -> list[SkillMetadata]:
        if not self.skills_root.is_dir():
            raise FileNotFoundError(f"Skills 目录不存在: {self.skills_root}")

        discovered: dict[str, SkillMetadata] = {}
        for skill_md in sorted(self.skills_root.glob("*/SKILL.md")):
            resolved = skill_md.resolve()
            if not resolved.is_relative_to(self.skills_root):
                raise ValueError(f"Skill 路径越界: {resolved}")
            frontmatter = self._read_frontmatter(resolved)
            name = str(frontmatter.get("name", "")).strip()
            description = str(frontmatter.get("description", "")).strip()
            if not name or not description:
                raise ValueError(f"Skill 缺少 name 或 description: {resolved}")
            if name in discovered:
                raise ValueError(f"Skill 名称重复: {name}")
            version = frontmatter.get("version")
            discovered[name] = SkillMetadata(
                name=name,
                description=description,
                version=str(version) if version is not None else None,
                base_dir=resolved.parent,
                skill_md_path=resolved,
            )

        self._skills = discovered
        return self.list()

    def list(self) -> list[SkillMetadata]:
        return [self._skills[name] for name in sorted(self._skills)]

    def get(self, name: str) -> SkillMetadata | None:
        return self._skills.get(name)

    def catalog_for_prompt(self) -> str:
        return "\n".join(
            f"- {skill.name}: {skill.description}" for skill in self.list()
        )

    def load_instructions(self, name: str) -> str:
        skill = self.get(name)
        if skill is None:
            raise KeyError(f"未知 Skill: {name}")
        return skill.skill_md_path.read_text(encoding="utf-8")

    @staticmethod
    def _read_frontmatter(path: Path) -> dict:
        text = path.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError(f"SKILL.md 缺少 YAML Frontmatter: {path}")
        try:
            end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        except StopIteration as exc:
            raise ValueError(f"SKILL.md Frontmatter 未闭合: {path}") from exc
        data = yaml.safe_load("\n".join(lines[1:end])) or {}
        if not isinstance(data, dict):
            raise ValueError(f"SKILL.md Frontmatter 必须是对象: {path}")
        return data
