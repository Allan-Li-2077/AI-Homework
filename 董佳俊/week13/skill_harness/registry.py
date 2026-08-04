"""
Skill Registry — 技能发现与注册（L0）

教学重点：
  1. 仅扫描 YAML frontmatter（name, description, version），不读正文
  2. 流式读取：遇到第二个 "---" 立即停止
  3. 不依赖 pyyaml，手写简单解析（skill frontmatter 足够简单）

使用方式：
    registry = SkillRegistry()
    registry.discover([Path("./skills")])
    all_skills = registry.list_skills()        # list[SkillMeta]
    skill = registry.get("baoyu-diagram")       # 按名称查找
"""

import re
import logging
from pathlib import Path

from .models import SkillMeta

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    技能注册表 — L0 快速扫描 + 内存缓存。

    Phase 0: discover() 扫描所有 SKILL.md 的 frontmatter
    Phase 1: 不涉及（匹配由 SkillMatcher 完成）
    内部缓存: name → SkillMeta 的快速查找表
    """

    def __init__(self):
        self._skills: dict[str, SkillMeta] = {}  # name → metadata
        self._discovered = False

    # ── Phase 0: 发现 ───────────────────────────────────────────────

    def discover(self, skill_dirs: list[Path]) -> int:
        """
        Phase 0: 扫描所有技能目录，仅解析 frontmatter。

        Args:
            skill_dirs: SKILL.md 所在的目录列表（如 [Path("./skills")]）

        Returns:
            发现的技能数量
        """
        self._skills.clear()
        for base_dir in skill_dirs:
            if not base_dir.exists():
                logger.debug(f"目录不存在，跳过: {base_dir}")
                continue
            for skill_dir in sorted(base_dir.iterdir()):
                if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                    continue
                meta = self._scan_frontmatter(skill_dir)
                if meta and meta.name not in self._skills:
                    self._skills[meta.name] = meta
                    logger.info(f"[Registry] 发现技能: {meta.name} (v{meta.version})")

        self._discovered = True
        logger.info(f"[Registry] 共发现 {len(self._skills)} 个技能")
        return len(self._skills)

    # ── 查询 ───────────────────────────────────────────────────────

    def list_skills(self) -> list[SkillMeta]:
        """返回所有已发现技能的元信息列表"""
        if not self._discovered:
            logger.warning("尚未执行 discover()，返回空列表")
        return list(self._skills.values())

    def get(self, name: str) -> SkillMeta | None:
        """按名称获取技能元信息"""
        return self._skills.get(name)

    def has(self, name: str) -> bool:
        """检查技能是否已注册"""
        return name in self._skills

    @property
    def skill_count(self) -> int:
        return len(self._skills)

    @property
    def is_discovered(self) -> bool:
        return self._discovered

    # ── 内部实现 ───────────────────────────────────────────────────

    @staticmethod
    def _scan_frontmatter(skill_dir: Path) -> SkillMeta | None:
        """
        流式读取 SKILL.md，仅解析 frontmatter（"---" 之间的 YAML）。

        读取策略：
        1. 打开文件
        2. 检查首行是否为 "---"
        3. 逐行读直到遇到第二个 "---"（frontmatter 结束）
        4. 立即停止，不读正文
        5. 手动解析 name / description / version
        """
        md_path = skill_dir / "SKILL.md"
        if not md_path.exists():
            return None

        try:
            with open(md_path, "r", encoding="utf-8") as f:
                # 检查首行是否为 frontmatter 开始标记
                first_line = f.readline().strip()
                if first_line != "---":
                    return None

                # 读取 frontmatter 内容（最多 30 行安全上限）
                fm_lines = []
                for line in f:
                    if line.strip() == "---":
                        break  # frontmatter 结束，停止读取
                    fm_lines.append(line)
                    if len(fm_lines) > 30:
                        break  # 安全上限，避免异常文件

        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"读取 {md_path} 失败: {e}")
            return None

        if not fm_lines:
            return None

        fm_text = "".join(fm_lines)
        name = SkillRegistry._parse_field(fm_text, "name")
        if not name:
            return None

        return SkillMeta(
            name=name,
            description=SkillRegistry._parse_field(fm_text, "description", ""),
            version=SkillRegistry._parse_field(fm_text, "version", ""),
            path=skill_dir,
        )

    @staticmethod
    def _parse_field(yaml_text: str, field: str, default: str = "") -> str:
        """
        从 YAML 文本中提取简单字段值。

        支持格式：
          field: value
          field: "value"
          field: 'value'
          field: >-           (多行折叠)
            long description
            spanning lines
        """
        # 匹配单行值
        pattern = rf"^{field}:\s*(.+)$"
        m = re.search(pattern, yaml_text, re.MULTILINE)
        if not m:
            return default

        value = m.group(1).strip()

        # 处理 YAML 块标量 (| 或 >)
        if value in ("|", "|-", ">-"):
            # 找到匹配行之后的位置
            start_pos = m.end()
            remaining = yaml_text[start_pos:]
            lines = []
            for line in remaining.split("\n"):
                if line and (line.startswith("  ") or line.startswith("\t")):
                    lines.append(line.strip())
                elif lines and not line.strip():
                    break  # 空行结束多行值
                elif lines and not line.startswith(" "):
                    break  # 非缩进行结束多行值
            result = " ".join(lines)
            return result.strip()

        # 处理引号包裹的值
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]

        return value
