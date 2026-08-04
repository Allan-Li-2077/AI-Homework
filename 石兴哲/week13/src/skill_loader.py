"""
渐进式 Skill 加载器

教学重点：
  1. 启动时只解析 YAML frontmatter（name + description），不加载 body
  2. LLM 判断 skill 相关时，通过 load_full() 按需加载完整内容
  3. Catalog 展示全部可用 skill，body 只在真正需要时才占用 context

数据流：
  scan_catalog() → 遍历 skills/*/SKILL.md → 解析 frontmatter → 返回 catalog
  load_full(name) → 读取指定 skill 的完整 SKILL.md → 返回 body + frontmatter

使用方式：
  from src.skill_loader import SkillLoader
  loader = SkillLoader("skills")
  catalog = loader.scan_catalog()
  # ... LLM 判断需要 code-review skill ...
  full_content = loader.load_full("code-review")
"""

import re
import yaml
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_SKILLS_DIR = Path(__file__).parent.parent / "skills"


@dataclass
class SkillInfo:
    """Skill 的元信息（来自 frontmatter）"""
    name: str
    description: str
    path: Path           # SKILL.md 的完整路径
    frontmatter: dict = field(default_factory=dict)  # 完整 frontmatter 数据
    body_loaded: bool = False  # body 是否已加载


class SkillLoader:
    """
    渐进式 Skill 加载器。

    设计原则：
    - scan_catalog() 只读 frontmatter（~100 tokens/skill），零浪费
    - load_full() 按需加载完整 SKILL.md body
    - 一旦加载过完整内容，body_loaded 标记为 True（可跳过重复加载）
    """

    def __init__(self, skills_dir: Path = DEFAULT_SKILLS_DIR):
        self.skills_dir = Path(skills_dir)
        self._catalog: list[SkillInfo] = []
        self._by_name: dict[str, SkillInfo] = {}

    # ── 扫描 Catalog（Level 0：只读 frontmatter）─────────────────────────────

    def scan_catalog(self) -> list[SkillInfo]:
        """
        遍历 skills/ 下的所有子目录，读取每个 SKILL.md 的 YAML frontmatter。
        不解析 body 内容——此时 model 还不知道具体指令。

        返回 SkillInfo 列表，按 name 排序。
        """
        self._catalog = []
        self._by_name = {}

        if not self.skills_dir.exists():
            logger.warning(f"Skills 目录不存在：{self.skills_dir}")
            return []

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            md_path = skill_dir / "SKILL.md"
            if not md_path.exists():
                logger.debug(f"跳过 {skill_dir.name}，无 SKILL.md")
                continue

            info = self._parse_frontmatter(md_path)
            if info:
                self._catalog.append(info)
                self._by_name[info.name] = info
                logger.info(f"[SkillLoader] 发现 skill：{info.name} — {info.description[:60]}")

        logger.info(f"[SkillLoader] 共扫描到 {len(self._catalog)} 个 skill（仅 frontmatter）")
        return self._catalog

    def _parse_frontmatter(self, md_path: Path) -> SkillInfo | None:
        """
        只解析 YAML frontmatter，不读取 body。

        SKILL.md 格式：
        ---
        name: xxx
        description: xxx
        ---
        # 正文内容...（此阶段不读取）
        """
        text = md_path.read_text(encoding="utf-8")
        # 找 frontmatter：第一个 --- 到第二个 --- 之间
        match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if not match:
            logger.warning(f"SKILL.md 无有效 frontmatter：{md_path}")
            return None

        try:
            fm = yaml.safe_load(match.group(1))
        except yaml.YAMLError as e:
            logger.warning(f"YAML 解析失败：{md_path} — {e}")
            return None

        if not isinstance(fm, dict):
            return None

        name = fm.get("name", md_path.parent.name)
        description = fm.get("description", "")
        if not description:
            logger.warning(f"SKILL.md 缺少 description：{md_path}")

        return SkillInfo(
            name=name,
            description=description,
            path=md_path,
            frontmatter=fm,
            body_loaded=False,
        )

    # ── 按需加载（Level 1：读取完整 body）─────────────────────────────────────

    def load_full(self, name: str) -> str | None:
        """
        读取指定 skill 的完整 SKILL.md 内容（含 frontmatter + body）。

        首次调用时读取文件；之后返回缓存，标记 body_loaded=True。
        """
        info = self._by_name.get(name)
        if not info:
            logger.warning(f"[SkillLoader] skill 不存在：{name}")
            return None

        full_text = info.path.read_text(encoding="utf-8")
        info.body_loaded = True
        logger.info(f"[SkillLoader] ✓ 加载完整 skill：{name}（{len(full_text)} 字符）")
        return full_text

    def get_body_only(self, name: str) -> str | None:
        """
        只返回 SKILL.md 的 body 部分（去掉 frontmatter）。
        用于 LLM 不需要再次看到 frontmatter 的场景。
        """
        info = self._by_name.get(name)
        if not info:
            return None
        text = info.path.read_text(encoding="utf-8")
        # 去掉 frontmatter 块
        body = re.sub(r"^---\s*\n.*?\n---\s*\n?", "", text, count=1, flags=re.DOTALL)
        info.body_loaded = True
        return body.strip()

    # ── 格式化输出 ────────────────────────────────────────────────────────────

    def get_catalog_text(self) -> str:
        """生成可注入 System Prompt 的 skill 目录文本（仅 frontmatter 摘要）"""
        if not self._catalog:
            return "（无可用 skill）"

        lines = []
        for info in self._catalog:
            status = "已加载" if info.body_loaded else "未加载"
            lines.append(f"- **{info.name}**: {info.description} ({status})")
        return "\n".join(lines)

    def get_skill_names(self) -> list[str]:
        return [info.name for info in self._catalog]

    def is_loaded(self, name: str) -> bool:
        info = self._by_name.get(name)
        return info.body_loaded if info else False
