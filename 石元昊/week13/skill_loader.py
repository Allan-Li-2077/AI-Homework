"""
Skill Loader — 渐进式加载引擎

教学重点：
  1. 三级加载策略：
     - Level 0（索引）：仅 frontmatter 元数据（Registry 阶段已完成）
     - Level 1（摘要）：SKILL.md 全文 + 附属文件清单
     - Level 2（完整）：SKILL.md + scripts/* + references/* + data/* 全部加载到内存
  2. 按需加载：只有被意图匹配选中的 skill 才会进入 Level 1/2
  3. 缓存机制：已加载的 skill 内容会被缓存，避免重复 IO

渐进式加载的核心价值：
  - 100 个 skill 全部加载 → 可能消耗 10MB+ context
  - 渐进式加载 → 只加载匹配的 1-2 个 skill，节省 95% 以上的 token
"""

import logging
from pathlib import Path
from dataclasses import dataclass, field

from src.skill_registry import SkillMeta, SkillRegistry

logger = logging.getLogger(__name__)


@dataclass
class LoadedSkill:
    """完整加载后的 Skill 对象"""
    meta: SkillMeta
    full_content: str = ""            # SKILL.md 全文
    scripts: dict[str, str] = field(default_factory=dict)     # {filename: content}
    references: dict[str, str] = field(default_factory=dict)  # {filename: content}
    data_files: dict[str, str] = field(default_factory=dict)  # {filename: content}

    @property
    def name(self) -> str:
        return self.meta.name

    @property
    def dir_path(self) -> Path:
        return self.meta.dir_path

    def summary(self) -> str:
        """返回加载情况摘要"""
        parts = [f"📦 {self.name} v{self.meta.version}"]
        parts.append(f"   SKILL.md: {len(self.full_content)} 字符")
        if self.scripts:
            parts.append(f"   脚本: {', '.join(self.scripts.keys())}")
        if self.references:
            parts.append(f"   参考: {', '.join(self.references.keys())}")
        if self.data_files:
            parts.append(f"   数据: {', '.join(self.data_files.keys())}")
        return "\n".join(parts)


class SkillLoader:
    """
    渐进式 Skill 加载器

    使用方式：
      loader = SkillLoader(registry)
      # Level 1: 加载 SKILL.md 全文
      skill = loader.load_level1("flash-card")
      # Level 2: 加载全部附属文件
      skill = loader.load_level2("flash-card")
    """

    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self._cache: dict[str, LoadedSkill] = {}  # name → LoadedSkill

    def load_level1(self, skill_name: str) -> LoadedSkill | None:
        """
        Level 1 加载：读取 SKILL.md 全文，不加载附属文件。
        适用于意图确认阶段——需要完整描述来判断是否匹配。
        """
        if skill_name in self._cache:
            cached = self._cache[skill_name]
            if cached.full_content:
                return cached

        meta = self.registry.get_skill(skill_name)
        if not meta:
            logger.warning(f"Skill 不存在：{skill_name}")
            return None

        full_content = meta.skill_md_path.read_text(encoding="utf-8")
        skill = LoadedSkill(meta=meta, full_content=full_content)
        self._cache[skill_name] = skill

        logger.info(f"[Level 1] 加载 {skill_name}：SKILL.md {len(full_content)} 字符")
        return skill

    def load_level2(self, skill_name: str) -> LoadedSkill | None:
        """
        Level 2 加载：SKILL.md + scripts/ + references/ + data/ 全部加载。
        适用于执行阶段——需要完整资源来运行 skill。
        """
        skill = self.load_level1(skill_name)
        if not skill:
            return None

        base = skill.meta.dir_path

        # 加载 scripts/
        if skill.meta.has_scripts and not skill.scripts:
            scripts_dir = base / "scripts"
            for f in sorted(scripts_dir.rglob("*")):
                if f.is_file() and f.name not in ("bun.lock",) and "node_modules" not in f.parts:
                    try:
                        skill.scripts[f.name] = f.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        skill.scripts[f.name] = f"<binary file: {f.name}>"

        # 加载 references/
        if skill.meta.has_references and not skill.references:
            refs_dir = base / "references"
            for f in sorted(refs_dir.iterdir()):
                if f.is_file():
                    skill.references[f.name] = f.read_text(encoding="utf-8")

        # 加载 data/
        if skill.meta.has_data and not skill.data_files:
            data_dir = base / "data"
            for f in sorted(data_dir.iterdir()):
                if f.is_file():
                    try:
                        skill.data_files[f.name] = f.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        skill.data_files[f.name] = f"<binary file: {f.name}>"

        logger.info(
            f"[Level 2] 加载 {skill_name}：scripts={len(skill.scripts)}, "
            f"references={len(skill.references)}, data={len(skill.data_files)}"
        )
        return skill

    def unload(self, skill_name: str):
        """从缓存中卸载一个 skill，释放内存"""
        if skill_name in self._cache:
            del self._cache[skill_name]
            logger.info(f"已卸载 skill：{skill_name}")

    def clear_cache(self):
        """清空所有缓存"""
        self._cache.clear()

    def get_cached(self, skill_name: str) -> LoadedSkill | None:
        """获取缓存中的 skill（不触发加载）"""
        return self._cache.get(skill_name)

    def get_loaded_names(self) -> list[str]:
        """返回当前已缓存的 skill 名称列表"""
        return list(self._cache.keys())

    def build_skill_context(self, skill_name: str) -> str:
        """
        构建注入 LLM 的 skill 上下文文本。
        Level 2 加载后，拼接 SKILL.md + 关键参考文件。
        """
        skill = self.load_level2(skill_name)
        if not skill:
            return ""

        parts = [skill.full_content]

        # 将 references 附在末尾（SKILL.md 中通常会引用这些文件）
        for fname, content in skill.references.items():
            parts.append(f"\n\n--- 参考文件：{fname} ---\n{content}")

        return "\n".join(parts)
