"""
渐进式加载器 — 技能的按需加载（L1 → L2 → L3）

教学重点：
  1. L1: SKILL.md 正文仅在匹配后才读取（延迟加载）
  2. L2: references/ 文件仅在明确引用时才读取（按需加载）
  3. L3: scripts/ 仅在 AI 决定调用时才执行（延迟执行）
  4. 内置缓存：同一 skill 不重复读取

使用方式：
    loader = SkillLoader()
    skill = loader.load_skill(meta)            # L1: 加载 SKILL.md 正文
    ref_content = loader.load_reference(skill, "architecture")  # L2: 按需加载参考
    scripts = loader.list_scripts(skill)        # 列出可用脚本
"""

import logging
from pathlib import Path

from .models import SkillMeta, Skill

logger = logging.getLogger(__name__)


class SkillLoader:
    """
    渐进式加载器 — 管理技能从 L0 到 L3 的完整加载生命周期。

    缓存机制：
      - _cache: 已加载的 Skill 对象，按 name 索引
      - 避免重复 I/O，同一 skill 多次请求只读一次
    """

    def __init__(self):
        self._cache: dict[str, Skill] = {}  # name → Skill

    # ── L1: 加载 SKILL.md 正文 ──────────────────────────────────────

    def load_skill(self, meta: SkillMeta) -> Skill:
        """
        L1: 加载 SKILL.md 完整内容（去除 frontmatter）。

        这是渐进式加载的第一个"重"操作 — 完整读取 SKILL.md 文件。
        仅对匹配到的 skill 调用，未匹配的 skill 永远不会到达这里。

        Args:
            meta: L0 阶段的 SkillMeta（含 skill 目录路径）

        Returns:
            完整的 Skill 对象（含 instructions, 已发现但未加载的 references/scripts 路径）
        """
        # 检查缓存
        if meta.name in self._cache:
            logger.info(f"[Loader] 从缓存返回: {meta.name}")
            return self._cache[meta.name]

        md_path = meta.path / "SKILL.md"
        logger.info(f"[Loader] L1 加载: {meta.name} ← {md_path}")

        try:
            full_text = md_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.error(f"[Loader] 读取 {md_path} 失败: {e}")
            # 返回空 Skill 作为降级
            skill = Skill(meta=meta, instructions="")
            self._cache[meta.name] = skill
            return skill

        # 去除 frontmatter（"---" 之间的部分）
        instructions = self._strip_frontmatter(full_text)

        # 扫描 references/ 和 scripts/ 目录（仅记录路径，不读内容）
        references = {}
        ref_dir = meta.path / "references"
        if ref_dir.exists():
            for f in sorted(ref_dir.iterdir()):
                if f.suffix in (".md",) and f.is_file():
                    references[f.name] = ""  # 占位，L2 按需填充

        scripts = []
        script_dir = meta.path / "scripts"
        if script_dir.exists() and script_dir.is_dir():
            for f in sorted(script_dir.iterdir()):
                if f.suffix in (".py", ".ts", ".js", ".sh") and f.is_file():
                    scripts.append(f)

        skill = Skill(
            meta=meta,
            instructions=instructions,
            references=references,
            scripts=scripts,
        )

        self._cache[meta.name] = skill
        logger.info(
            f"[Loader] 加载完成: {meta.name} "
            f"(指令 {len(instructions)} 字符, "
            f"{len(references)} 个参考文件, "
            f"{len(scripts)} 个脚本)"
        )
        return skill

    # ── L2: 按需加载参考文件 ────────────────────────────────────────

    def load_reference(self, skill: Skill, ref_name: str) -> str | None:
        """
        L2: 按需加载单个参考文件。

        仅在 skill 的指令执行流程中明确引用了该参考文件时才调用。
        例如，当 baoyu-diagram 的指令说"→ 阅读 references/flowchart.md"时，
        调用 load_reference(skill, "flowchart.md") 触发实际读取。

        Args:
            skill: 已加载的 Skill 对象
            ref_name: 参考文件名（如 "flowchart.md"）

        Returns:
            文件内容，若文件不存在则返回 None
        """
        # 检查缓存（已加载的参考文件）
        if skill.references.get(ref_name, ""):
            logger.info(f"[Loader] L2 从缓存返回: {ref_name}")
            return skill.references[ref_name]

        ref_path = skill.meta.path / "references" / ref_name
        if not ref_path.exists():
            # 尝试不带 .md 扩展名
            if not ref_name.endswith(".md"):
                ref_path = skill.meta.path / "references" / f"{ref_name}.md"
                if not ref_path.exists():
                    logger.warning(f"[Loader] 参考文件不存在: {ref_name}")
                    return None
            else:
                logger.warning(f"[Loader] 参考文件不存在: {ref_name}")
                return None

        logger.info(f"[Loader] L2 按需加载参考: {ref_path.name} ({ref_path.stat().st_size} 字节)")

        try:
            content = ref_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.error(f"[Loader] 读取参考文件失败: {e}")
            return None

        # 缓存到 skill.references（用实际文件名做 key）
        skill.references[ref_path.name] = content
        return content

    # ── 脚本相关 ────────────────────────────────────────────────────

    def list_scripts(self, skill: Skill) -> list[Path]:
        """返回 skill 的可用脚本路径列表"""
        return skill.scripts

    def get_script_path(self, skill: Skill, script_name: str) -> Path | None:
        """根据脚本名称获取脚本路径"""
        for sp in skill.scripts:
            if sp.name == script_name or sp.stem == script_name:
                return sp
        return None

    # ── 缓存管理 ────────────────────────────────────────────────────

    def clear_cache(self):
        """清除所有缓存的技能定义"""
        self._cache.clear()
        logger.info("[Loader] 缓存已清除")

    def stats(self) -> dict:
        """返回加载器统计信息"""
        total_refs_loaded = sum(
            1 for s in self._cache.values()
            for v in s.references.values() if v
        )
        return {
            "cached_skills": len(self._cache),
            "total_references_loaded": total_refs_loaded,
            "cached_names": list(self._cache.keys()),
        }

    # ── 内部工具 ────────────────────────────────────────────────────

    @staticmethod
    def _strip_frontmatter(text: str) -> str:
        """
        去除 YAML frontmatter，返回 Markdown 正文。

        SKILL.md 格式：
          ---
          name: xxx
          description: xxx
          ---

          # 正文标题
          正文内容...
        """
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return text.strip()
