
import re
from pathlib import Path
from dataclasses import dataclass, field

SKILLS_DIR = Path(__file__).parent.parent / "skills"

@dataclass
class SkillIndex:
    name: str
    description: str
    skill_dir: Path
    skill_md: Path

@dataclass
class SkillDetail:
    """Level 1：完整指令"""
    index: SkillIndex
    instructions: str   # SKILL.md 去掉 frontmatter 后的正文

class SkillLoader:
    def __init__(self, skills_dir: Path = SKILLS_DIR):
        self.skills_dir = skills_dir
        self._cache: dict[str, SkillIndex] = {}  # name → index
    # ── Level 0: 扫描索引 ──────────────────────────────
    def scan(self) -> list[SkillIndex]:
        """遍历 skills/*/SKILL.md，只解析 frontmatter"""
        result = []
        for md_path in sorted(self.skills_dir.glob("*/SKILL.md")):
            frontmatter = self._parse_frontmatter(md_path)
            idx = SkillIndex(
                name=frontmatter.get("name", md_path.parent.name),
                description=frontmatter.get("description", ""),
                skill_dir=md_path.parent,
                skill_md=md_path,
            )
            self._cache[idx.name] = idx
            result.append(idx)
        return result
    def _parse_frontmatter(self, path: Path) -> dict:
        """解析 YAML frontmatter（--- 之间的部分）"""
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not m:
            return {}
        raw = m.group(1)
        # 简单解析 name: xxx 和 description: >- 多行
        meta = {}
        # name 是单行
        name_m = re.search(r"^name:\s*(.+)$", raw, re.MULTILINE)
        if name_m:
            meta["name"] = name_m.group(1).strip()
        # description 支持 >- 多行折叠
        desc_m = re.search(r"^description:\s*>-?\s*\n((?:\s+.+\n?)+)", raw, re.MULTILINE)
        if desc_m:
            lines = [l.strip() for l in desc_m.group(1).strip().splitlines()]
            meta["description"] = " ".join(lines)
        else:
            desc_m = re.search(r"^description:\s*(.+)$", raw, re.MULTILINE)
            if desc_m:
                meta["description"] = desc_m.group(1).strip()
        return meta
    # ── Level 0 → system prompt 注入文本 ─────────────────
    def build_index_prompt(self) -> str:
        """生成注入 system prompt 的技能索引（几十 token）"""
        skills = self.scan()
        if not skills:
            return ""
        lines = ["## 可用技能（当用户请求匹配某技能时，回复 SKILL_TRIGGER:<技能名>）"]
        for s in skills:
            lines.append(f"- {s.name}: {s.description}")
        lines.append("")
        lines.append("如果用户请求匹配某技能，在回答最开头输出 SKILL_TRIGGER:<技能名>，然后正常回答。")
        lines.append("如果不匹配任何技能，直接正常回答，不要输出 SKILL_TRIGGER。")
        lines.append(
            "当触发技能时，必须在回答中包含 ```json 代码块（数据）和 ```bash 代码块（命令），不要只用文字描述操作结果。")
        return "\n".join(lines)
    # ── Level 1: 按需加载完整指令 ────────────────────────
    def load_detail(self, name: str) -> SkillDetail | None:
        """命中后加载完整 SKILL.md 正文"""
        idx = self._cache.get(name)
        if not idx:
            # 重新扫描一次
            self.scan()
            idx = self._cache.get(name)
        if not idx:
            return None
        text = idx.skill_md.read_text(encoding="utf-8")
        # 去掉 frontmatter，保留正文
        body = re.sub(r"^---\n.*?\n---\s*", "", text, flags=re.DOTALL).strip()
        return SkillDetail(index=idx, instructions=body)

