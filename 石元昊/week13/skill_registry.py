"""
Skill Registry — Skill 发现与元数据索引

教学重点：
  1. 扫描 skills/ 目录，自动发现所有含 SKILL.md 的子目录
  2. 只解析 SKILL.md 的 YAML frontmatter（name, description, version），不加载完整内容
  3. 维护一个轻量级的 Skill 索引表，供意图检测阶段快速查找

渐进式加载第一阶段：只读 frontmatter，几十毫秒完成全部 skill 的索引。
"""

import re
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 默认 skills 目录：homework 的上级目录下的 skills/
DEFAULT_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"


@dataclass
class SkillMeta:
    """Skill 的轻量级元数据（仅 frontmatter）"""
    name: str
    description: str
    version: str
    dir_path: Path        # skill 目录的绝对路径
    skill_md_path: Path   # SKILL.md 的绝对路径

    # 可选的附属目录/文件
    has_scripts: bool = False
    has_references: bool = False
    has_data: bool = False

    def __post_init__(self):
        self.has_scripts = (self.dir_path / "scripts").is_dir()
        self.has_references = (self.dir_path / "references").is_dir()
        self.has_data = (self.dir_path / "data").is_dir()


def _parse_frontmatter(text: str) -> dict:
    """
    解析 YAML frontmatter（--- ... --- 之间的内容）。
    不用 PyYAML 依赖，手写简单解析器，够用且零依赖。
    """
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}

    body = m.group(1)
    result = {}
    current_key = None
    multiline_buf: list[str] = []

    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if current_key and multiline_buf is not None:
                multiline_buf.append(line)
            continue

        # 检测 "key: value" 或 "key: >-" 多行
        kv = re.match(r"^(\w[\w-]*)\s*:\s*(.*)", line)
        if kv:
            # 先把上一个多行字段收掉
            if current_key and multiline_buf:
                result[current_key] = "\n".join(multiline_buf).strip()

            key, val = kv.group(1), kv.group(2).strip()
            if val in (">-", "|", ">"):
                current_key = key
                multiline_buf = []
            else:
                result[key] = val.strip('"').strip("'")
                current_key = None
                multiline_buf = []
        else:
            # 多行续行
            if current_key is not None:
                multiline_buf.append(stripped)

    # 收尾
    if current_key and multiline_buf:
        result[current_key] = "\n".join(multiline_buf).strip()

    return result


class SkillRegistry:
    """
    Skill 注册表：扫描 skills 目录，建立轻量元数据索引。

    使用方式：
      registry = SkillRegistry()
      registry.discover()
      for meta in registry.list_skills():
          print(meta.name, meta.description[:50])
    """

    def __init__(self, skills_dir: Path = DEFAULT_SKILLS_DIR):
        self.skills_dir = skills_dir
        self._skills: dict[str, SkillMeta] = {}  # name → SkillMeta

    def discover(self) -> int:
        """
        扫描 skills_dir 下所有子目录，解析 SKILL.md frontmatter。
        返回发现的 skill 数量。
        """
        self._skills.clear()

        if not self.skills_dir.exists():
            logger.warning(f"Skills 目录不存在：{self.skills_dir}")
            return 0

        count = 0
        for child in sorted(self.skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                text = skill_md.read_text(encoding="utf-8")
                fm = _parse_frontmatter(text)
                name = fm.get("name", child.name)
                meta = SkillMeta(
                    name=name,
                    description=fm.get("description", ""),
                    version=fm.get("version", "0.0.0"),
                    dir_path=child,
                    skill_md_path=skill_md,
                )
                self._skills[name] = meta
                count += 1
                logger.info(f"发现 skill：{name} v{meta.version}")
            except Exception as e:
                logger.error(f"解析 {skill_md} 失败：{e}")

        logger.info(f"共发现 {count} 个 skills")
        return count

    def list_skills(self) -> list[SkillMeta]:
        """返回所有已注册的 skill 元数据"""
        return list(self._skills.values())

    def get_skill(self, name: str) -> SkillMeta | None:
        """按名称查找 skill"""
        return self._skills.get(name)

    def get_skill_names(self) -> list[str]:
        return list(self._skills.keys())

    def get_skill_descriptions(self) -> dict[str, str]:
        """返回 {name: description} 映射，供意图检测使用"""
        return {name: meta.description for name, meta in self._skills.items()}
