"""
技能加载器 — 渐进式（懒加载）技能发现与管理

特性：
- 启动时仅扫描目录、构建索引（不读取 SKILL.md）
- 首次调用时解析 SKILL.md、缓存
- 支持 TTL 过期自动卸载
- 支持 hot-reload（文件变更检测）
"""

import logging
import re
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import HarnessConfig

logger = logging.getLogger("harness.skill_loader")

# ── YAML frontmatter 解析（零依赖实现，避免 PyYAML 依赖）──

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class Skill:
    """技能实例"""

    name: str
    """技能名称（目录名）"""

    description: str = ""
    """技能描述（来自 SKILL.md frontmatter）"""

    version: str = "0.0.0"
    """技能版本（来自 SKILL.md frontmatter）"""

    path: Path = field(default_factory=Path)
    """技能目录绝对路径"""

    spec: str = ""
    """SKILL.md 完整内容（懒加载后填充，空字符串表示未加载）"""

    scripts: list[str] = field(default_factory=list)
    """可用脚本路径列表（相对于 skill 目录）"""

    references: list[str] = field(default_factory=list)
    """参考文档路径列表（相对于 skill 目录）"""

    loaded_at: Optional[datetime] = None
    """最后一次加载时间"""

    load_count: int = 0
    """加载/使用次数"""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    """线程安全锁"""

    @property
    def is_loaded(self) -> bool:
        return bool(self.spec)

    @property
    def age_seconds(self) -> float:
        """自上次加载以来的秒数"""
        if self.loaded_at is None:
            return float("inf")
        return (datetime.now() - self.loaded_at).total_seconds()

    def to_tool_schema(self) -> dict:
        """将此技能转换为 OpenAI function calling tool schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description or f"执行技能: {self.name}",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "instruction": {
                            "type": "string",
                            "description": "要传递给该技能的指令或问题描述",
                        }
                    },
                    "required": ["instruction"],
                },
            },
        }

    def __repr__(self) -> str:
        status = "loaded" if self.is_loaded else "indexed"
        return f"Skill({self.name!r}, {status}, v{self.version})"


class SkillLoader:
    """
    渐进式技能加载器

    工作流程：
    1. discover() — 扫描目录，构建 Skill 索引（仅 name + description）
    2. load(skill_name) — 按需加载完整 SKILL.md
    3. unload(skill_name) — TTL 过期后卸载缓存
    4. reload(skill_name) — 检测变更后热重载
    """

    def __init__(self, config: HarnessConfig):
        self.config = config
        self._index: dict[str, Skill] = {}        # name → Skill
        self._scripts_cache: dict[str, list[str]] = {}  # name → script paths
        self._mtime_cache: dict[str, float] = {}   # path → last mtime
        self._index_lock = threading.RLock()

    # ── 目录扫描与索引构建 ────────────────────────────────

    def discover(self) -> dict[str, Skill]:
        """扫描技能目录，构建索引。仅读取 frontmatter，不加载完整 spec。"""
        skills_dir = self.config.skills_path
        if not skills_dir.is_dir():
            logger.warning("技能目录不存在: %s", skills_dir)
            return {}

        with self._index_lock:
            self._index.clear()
            self._scripts_cache.clear()

            for entry in sorted(skills_dir.iterdir()):
                if not entry.is_dir():
                    continue

                skill_md = entry / "SKILL.md"
                if not skill_md.is_file():
                    logger.debug("跳过无 SKILL.md 的目录: %s", entry.name)
                    continue

                try:
                    skill = self._index_skill(entry, skill_md)
                    self._index[skill.name] = skill
                    logger.info("发现技能: %s (v%s)", skill.name, skill.version)
                except Exception as e:
                    logger.error("索引技能 %s 失败: %s", entry.name, e)

        logger.info("技能索引构建完成，共 %d 个技能", len(self._index))
        return dict(self._index)

    def _index_skill(self, skill_dir: Path, skill_md: Path) -> Skill:
        """仅解析 frontmatter 构建轻量索引"""
        name = skill_dir.name
        description = ""
        version = "0.0.0"

        # 只读前几行获取 frontmatter
        try:
            with open(skill_md, "r", encoding="utf-8") as f:
                head = f.read(4096)  # 前 4KB 足够解析 frontmatter
        except Exception:
            head = ""

        match = _FRONTMATTER_RE.match(head)
        if match:
            fm = self._parse_frontmatter(match.group(1))
            description = fm.get("description", "")
            version = fm.get("version", "0.0.0")

        # 扫描脚本和参考文件
        scripts = self._discover_scripts(skill_dir)
        references = self._discover_references(skill_dir)

        skill = Skill(
            name=name,
            description=description,
            version=version,
            path=skill_dir.resolve(),
            scripts=scripts,
            references=references,
        )
        return skill

    @staticmethod
    def _parse_frontmatter(yaml_text: str) -> dict:
        """简易 YAML 解析器，仅支持顶层 key: value"""
        result = {}
        for line in yaml_text.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                # 处理多行 >- 值（简化处理：取第一行）
                if val == ">-" or val == ">":
                    continue  # 多行值跳过，实际使用时 description 已经可以了
                result[key] = val
        return result

    def _discover_scripts(self, skill_dir: Path) -> list[str]:
        """发现技能目录下的可执行脚本（排除 node_modules 和 __pycache__）"""
        scripts = []
        for ext in self.config.allowed_script_extensions:
            for p in skill_dir.glob(f"scripts/**/*{ext}"):
                # 排除 node_modules 和 __pycache__ 中的文件
                parts = p.parts
                if "node_modules" in parts or "__pycache__" in parts:
                    continue
                scripts.append(str(p.relative_to(skill_dir)))
        return sorted(scripts)

    def _discover_references(self, skill_dir: Path) -> list[str]:
        """发现参考文档"""
        refs = []
        refs_dir = skill_dir / "references"
        if refs_dir.is_dir():
            for p in refs_dir.glob("*.md"):
                refs.append(str(p.relative_to(skill_dir)))
        return sorted(refs)

    # ── 懒加载 ────────────────────────────────────────────

    def load(self, name: str) -> Optional[Skill]:
        """
        按需加载技能完整 spec。

        如果技能已加载且未过期，直接返回缓存。
        如果 TTL 已过，重新从磁盘读取。
        """
        with self._index_lock:
            skill = self._index.get(name)
            if skill is None:
                logger.warning("技能未注册: %s", name)
                return None

        # 快速路径：已加载且未过期
        if skill.is_loaded:
            if self._is_cache_valid(skill):
                return skill
            # 过期 → 重新加载
            logger.debug("技能缓存过期，重新加载: %s", name)

        # 加载 SKILL.md 完整内容
        with skill._lock:
            skill_md = skill.path / "SKILL.md"
            try:
                spec = skill_md.read_text(encoding="utf-8")
                skill.spec = spec
                skill.loaded_at = datetime.now()
                skill.load_count += 1
                self._mtime_cache[str(skill_md)] = skill_md.stat().st_mtime
                logger.info("技能加载完成: %s (%d 字符)", name, len(spec))
                return skill
            except Exception as e:
                logger.error("加载技能 %s 失败: %s", name, e)
                return None

    def _is_cache_valid(self, skill: Skill) -> bool:
        """检查缓存的技能是否仍然有效"""
        ttl = self.config.cache_ttl_seconds
        if ttl > 0 and skill.age_seconds > ttl:
            return False

        if self.config.hot_reload:
            skill_md = skill.path / "SKILL.md"
            if skill_md.is_file():
                current_mtime = skill_md.stat().st_mtime
                cached = self._mtime_cache.get(str(skill_md), 0)
                if current_mtime > cached:
                    logger.info("检测到 SKILL.md 变更: %s", skill.name)
                    return False

        return True

    def unload(self, name: str) -> bool:
        """卸载技能缓存（释放内存）"""
        with self._index_lock:
            skill = self._index.get(name)
            if skill is None:
                return False

        with skill._lock:
            skill.spec = ""
            skill.loaded_at = None
            logger.debug("技能已卸载: %s", name)
            return True

    def reload(self, name: str) -> Optional[Skill]:
        """强制重新加载技能"""
        self.unload(name)
        return self.load(name)

    def unload_expired(self) -> int:
        """卸载所有过期技能，返回卸载数量"""
        if self.config.cache_ttl_seconds <= 0:
            return 0
        count = 0
        for name in list(self._index.keys()):
            skill = self._index[name]
            if skill.is_loaded and not self._is_cache_valid(skill):
                self.unload(name)
                count += 1
        return count

    # ── 查询接口 ──────────────────────────────────────────

    def get(self, name: str) -> Optional[Skill]:
        """获取技能索引条目（不触发加载）"""
        return self._index.get(name)

    def list_all(self) -> list[Skill]:
        """列出所有已索引的技能"""
        return sorted(self._index.values(), key=lambda s: s.name)

    def list_loaded(self) -> list[Skill]:
        """列出当前已加载到内存的技能"""
        return [s for s in self._index.values() if s.is_loaded]

    def list_names(self) -> list[str]:
        """列出所有技能名称"""
        return sorted(self._index.keys())

    def list_tool_schemas(self, names: Optional[list[str]] = None) -> list[dict]:
        """
        生成 OpenAI tool schemas 列表。

        Args:
            names: 要包含的技能名称列表，None=所有已索引技能
        """
        if names is None:
            names = list(self._index.keys())
        schemas = []
        for name in names:
            skill = self._index.get(name)
            if skill:
                schemas.append(skill.to_tool_schema())
        return schemas

    def read_reference(self, skill_name: str, ref_path: str) -> Optional[str]:
        """
        读取技能的参考文档。

        Args:
            skill_name: 技能名称
            ref_path: 参考文档路径（相对于技能目录）
        """
        skill = self._index.get(skill_name)
        if skill is None:
            return None
        ref_file = skill.path / ref_path
        if ref_file.is_file():
            return ref_file.read_text(encoding="utf-8")
        return None

    @property
    def index_size(self) -> int:
        return len(self._index)

    @property
    def loaded_count(self) -> int:
        return len(self.list_loaded())
