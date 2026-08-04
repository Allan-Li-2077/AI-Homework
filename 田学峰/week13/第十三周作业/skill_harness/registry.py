from __future__ import annotations

from pathlib import Path

from .frontmatter import read_frontmatter
from .models import SkillMetadata


class SkillRegistry:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir

    def discover(self) -> list[SkillMetadata]:
        # 只扫描 */SKILL.md，并且只读取每个文件开头的 frontmatter。
        # 这是渐进式加载的第一步：先轻量发现，不急着加载大正文。
        skills: list[SkillMetadata] = []
        if not self.skills_dir.exists():
            raise FileNotFoundError(f"skills 目录不存在: {self.skills_dir}")

        for skill_file in sorted(self.skills_dir.glob("*/SKILL.md")):
            fields, chars = read_frontmatter(skill_file)
            name = fields.get("name") or skill_file.parent.name
            description = fields.get("description", "")
            version = fields.get("version")
            skills.append(
                SkillMetadata(
                    name=name,
                    description=description,
                    version=version,
                    root=skill_file.parent,
                    skill_file=skill_file,
                    frontmatter_chars=chars,
                )
            )
        return skills

    def get(self, name: str) -> SkillMetadata:
        # 允许用 frontmatter 里的 name，也允许用目录名来找 skill。
        normalized = name.strip().lower()
        for skill in self.discover():
            if skill.name.lower() == normalized or skill.root.name.lower() == normalized:
                return skill
        raise KeyError(f"找不到 skill: {name}")
