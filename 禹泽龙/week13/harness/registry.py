"""Skill 注册表：扫描 skills/ 目录，建立索引（仅 name + description）"""

from __future__ import annotations

import re
import yaml
from pathlib import Path

from .skill import Skill


class SkillRegistry:
    """管理所有 skills，支持懒加载"""

    def __init__(self, skills_root: str | Path):
        self.skills_root = Path(skills_root)
        self._skills: dict[str, Skill] = {}  # name -> Skill
        self._scan()

    # ------------------------------------------------------------------ #
    #  启动时扫描：只解析 frontmatter 中的 name + description           #
    # ------------------------------------------------------------------ #
    def _scan(self) -> None:
        """扫描 skills_root 下所有 SKILL.md，建立轻量索引"""
        self._skills.clear()

        if not self.skills_root.exists():
            return

        for skill_dir in self.skills_root.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            name, description = self._extract_name_desc(skill_md)
            if not name:
                continue

            self._skills[name] = Skill(
                name=name,
                description=description,
                path=skill_dir,
            )

    def _extract_name_desc(self, skill_md: Path) -> tuple[str, str]:
        """只读取 SKILL.md 的 frontmatter，提取 name + description"""
        try:
            lines = skill_md.read_text(encoding="utf-8").splitlines()
        except Exception:
            return "", ""

        # 找 frontmatter 边界
        if not (lines and lines[0].strip() == "---"):
            return "", ""

        fence_end = -1
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                fence_end = i
                break

        if fence_end <= 1:
            return "", ""

        try:
            meta = yaml.safe_load("\n".join(lines[1:fence_end]))
            name = str(meta.get("name", "") or "")
            desc = str(meta.get("description", "") or "")
            return name, desc
        except Exception:
            return "", ""

    # ------------------------------------------------------------------ #
    #  对外 API                                                           #
    # ------------------------------------------------------------------ #
    def list_skills(self) -> list[Skill]:
        """返回所有已扫描的 skills（不触发加载）"""
        return list(self._skills.values())

    def get_skill(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def find_relevant_skills(self, query: str, top_k: int = 3) -> list[Skill]:
        """
        根据用户问题找到最相关的 skill（不加载完整内容）。
        同时支持中文和英文关键词匹配，按匹配度排序。
        """
        query_lower = query.lower().strip()
        scored = []

        is_chinese = any('一' <= c <= '鿿' for c in query)
        desc_lower_by_skill = {s.name: s.description.lower() for s in self._skills.values()}

        for skill in self._skills.values():
            desc_lower = desc_lower_by_skill[skill.name]

            if is_chinese:
                # 中文：检查 query 是否作为子串出现在 description 中
                score = 0
                if query_lower in desc_lower:
                    score += 20  # 完整子串匹配，高权重
                # 检查 description 是否包含 query 中的关键中文字符（连续2个以上）
                for i in range(len(query_lower) - 1):
                    bigram = query_lower[i:i+2]
                    if bigram in desc_lower:
                        score += 1
            else:
                # 英文：按空格分词
                score = sum(1 for word in query_lower.split() if word in desc_lower)
                if query_lower in desc_lower:
                    score += 10

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:top_k]]

    def load_skill(self, name: str) -> Skill | None:
        """显式加载某个 skill 的完整内容"""
        skill = self._skills.get(name)
        if skill:
            skill.load()
        return skill
