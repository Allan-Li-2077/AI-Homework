"""
上下文协议管理器 — SOUL / AGENTS / HEARTBEAT / MEMORY / USER

实现 awareness 协议的五层上下文：
- SOUL.md: Agent 人格定义 (who you are)
- AGENTS.md: 操作手册 (how you work)
- HEARTBEAT.md: 定时任务 (what to do periodically)
- MEMORY.md: 跨会话记忆 (what you remember)
- USER.md: 用户画像 (who you serve)

支持：
- 文件监听与热重载
- 记忆压缩（条目超阈值时合并旧条目）
- MEMORY.md 的 add/replace/remove 操作
"""

import logging
import hashlib
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import HarnessConfig

logger = logging.getLogger("harness.awareness")

# ── 协议文件名 ──────────────────────────────────────────

PROTOCOL_FILES = {
    "soul":      "SOUL.md",
    "agents":    "AGENTS.md",
    "heartbeat": "HEARTBEAT.md",
    "memory":    "MEMORY.md",
    "user":      "USER.md",
}


class AwarenessManager:
    """
    上下文协议管理器

    使用方式：
        am = AwarenessManager(config)
        am.load_all()                  # 启动时加载所有协议文件
        system_prompt = am.build_system_prompt()  # 构建系统 prompt
    """

    def __init__(self, config: HarnessConfig):
        self.config = config
        self._cache: dict[str, str] = {}          # key → content
        self._mtime: dict[str, float] = {}         # file_path → mtime
        self._lock = threading.RLock()

    # ── 文件加载 ──────────────────────────────────────────

    def load_all(self) -> dict[str, str]:
        """加载所有协议文件"""
        with self._lock:
            self._cache.clear()
            awareness_dir = self.config.awareness_path

            if not awareness_dir.is_dir():
                logger.warning("awareness 目录不存在: %s", awareness_dir)
                # 自动创建目录和空文件
                awareness_dir.mkdir(parents=True, exist_ok=True)
                for key, filename in PROTOCOL_FILES.items():
                    default_content = self._default_content(key)
                    filepath = awareness_dir / filename
                    if not filepath.exists():
                        filepath.write_text(default_content, encoding="utf-8")
                        logger.info("创建默认协议文件: %s", filename)

            for key, filename in PROTOCOL_FILES.items():
                filepath = awareness_dir / filename
                if filepath.is_file():
                    try:
                        content = filepath.read_text(encoding="utf-8")
                        self._cache[key] = content
                        self._mtime[str(filepath)] = filepath.stat().st_mtime
                        logger.debug("加载协议文件: %s (%d 字符)", filename, len(content))
                    except Exception as e:
                        logger.error("读取 %s 失败: %s", filename, e)
                        self._cache[key] = ""
                else:
                    # 创建默认文件
                    default = self._default_content(key)
                    filepath.write_text(default, encoding="utf-8")
                    self._cache[key] = default
                    self._mtime[str(filepath)] = filepath.stat().st_mtime

        total_chars = sum(len(v) for v in self._cache.values())
        logger.info("协议加载完成，共 %d 个文件，%d 字符", len(self._cache), total_chars)
        return dict(self._cache)

    def reload_if_changed(self) -> list[str]:
        """检测文件变更并热重载，返回变更的文件 key 列表"""
        changed = []
        awareness_dir = self.config.awareness_path

        for key, filename in PROTOCOL_FILES.items():
            filepath = awareness_dir / filename
            if not filepath.is_file():
                continue

            current_mtime = filepath.stat().st_mtime
            cached = self._mtime.get(str(filepath), 0)
            if current_mtime > cached:
                try:
                    content = filepath.read_text(encoding="utf-8")
                    with self._lock:
                        self._cache[key] = content
                        self._mtime[str(filepath)] = current_mtime
                    changed.append(key)
                    logger.info("协议文件变更重载: %s", filename)
                except Exception as e:
                    logger.error("重载 %s 失败: %s", filename, e)

        return changed

    @staticmethod
    def _default_content(key: str) -> str:
        """各协议文件的默认内容"""
        defaults = {
            "soul": (
                "# SOUL.md — 人格定义\n\n"
                "你是 Harness Agent，一个基于渐进式技能加载框架的智能助手。\n\n"
                "## 风格\n"
                "- 简洁、直接\n"
                "- 中文优先\n"
                "- 主动但不越界\n"
            ),
            "agents": (
                "# AGENTS.md — 操作手册\n\n"
                "## 核心规则\n"
                "1. 先理解用户意图，再行动\n"
                "2. 优先使用已有技能，而非从零实现\n"
                "3. 每一步思考都应该可见（ReAct Thought）\n"
                "4. 不确定时主动询问，而非猜测\n\n"
                "## 技能使用\n"
                "- 技能按需加载，不需要预加载所有技能\n"
                "- 使用技能前先加载其 SKILL.md 了解完整规格\n"
            ),
            "heartbeat": (
                "# HEARTBEAT.md — 定时任务\n\n"
                "## 定时任务列表\n"
                "暂无。使用 `harness heartbeat add` 添加。\n\n"
                "### 格式\n"
                "```\n"
                "## [名称]\n"
                "- **schedule**: cron/interval\n"
                "- **action**: 执行的动作描述\n"
                "- **enabled**: true/false\n"
                "```\n"
            ),
            "memory": (
                "# MEMORY.md — 跨会话记忆\n\n"
                "暂无记忆条目。\n"
            ),
            "user": (
                "# USER.md — 用户画像\n\n"
                "暂无用户画像。Agent 会在交互中逐步学习并填充。\n"
            ),
        }
        return defaults.get(key, "")

    # ── 内容访问 ──────────────────────────────────────────

    def get(self, key: str) -> str:
        """获取指定协议内容"""
        return self._cache.get(key, "")

    def get_soul(self) -> str:
        return self._cache.get("soul", "")

    def get_agents(self) -> str:
        return self._cache.get("agents", "")

    def get_heartbeat(self) -> str:
        return self._cache.get("heartbeat", "")

    def get_memory(self) -> str:
        return self._cache.get("memory", "")

    def get_user(self) -> str:
        return self._cache.get("user", "")

    # ── 系统 Prompt 构建 ──────────────────────────────────

    def build_system_prompt(self, include_memory: bool = True) -> str:
        """
        构建完整的系统提示词。

        拼接顺序：SOUL → AGENTS → USER → MEMORY
        """
        self.reload_if_changed()  # 先检查热更新

        parts = []

        soul = self.get_soul()
        if soul.strip():
            parts.append(soul.strip())

        agents = self.get_agents()
        if agents.strip():
            parts.append(agents.strip())

        user = self.get_user()
        if user.strip():
            parts.append(user.strip())

        if include_memory:
            memory = self.get_memory()
            if memory.strip():
                parts.append(memory.strip())

        return "\n\n".join(parts)

    def get_skills_section(self, skill_names: list[str], loader=None) -> str:
        """
        生成技能列表段落，可附加到系统 prompt。

        Args:
            skill_names: 可用的技能名称列表
            loader: SkillLoader 实例，用于获取技能描述
        """
        lines = ["## 可用技能", ""]
        for name in skill_names:
            if loader:
                skill = loader.get(name)
                if skill:
                    desc = skill.description or "(无描述)"
                    lines.append(f"- **{name}**: {desc}")
                else:
                    lines.append(f"- **{name}**")
            else:
                lines.append(f"- **{name}**")
        lines.append("")
        lines.append("使用技能前先调用对应的工具函数，系统会自动加载完整的技能规格。")
        return "\n".join(lines)

    # ── MEMORY.md 操作 ────────────────────────────────────

    def memory_add(self, entry: str) -> bool:
        """向 MEMORY.md 追加一条记忆"""
        filepath = self.config.awareness_path / "MEMORY.md"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_line = f"\n- [{timestamp}] {entry}"

        try:
            content = filepath.read_text(encoding="utf-8")
            content = content.rstrip() + new_line + "\n"
            filepath.write_text(content, encoding="utf-8")
            self._cache["memory"] = content
            self._mtime[str(filepath)] = filepath.stat().st_mtime
            logger.info("记忆已添加: %s", entry[:50])
            return True
        except Exception as e:
            logger.error("写入 MEMORY.md 失败: %s", e)
            return False

    def memory_search(self, query: str) -> list[str]:
        """
        在 MEMORY.md 中搜索相关记忆（简单关键词匹配）。

        Args:
            query: 搜索关键词

        Returns:
            匹配的条目列表
        """
        content = self.get_memory()
        if not content:
            return []

        results = []
        for line in content.split("\n"):
            if query.lower() in line.lower() and line.strip().startswith("- ["):
                results.append(line.strip())
        return results

    def memory_compact(self, keep_recent: int = 20) -> int:
        """
        压缩记忆：保留最近 N 条，合并旧条目。

        Returns:
            移除的条目数
        """
        filepath = self.config.awareness_path / "MEMORY.md"
        content = self.get_memory()
        if not content:
            return 0

        lines = content.split("\n")
        entries = [l for l in lines if l.strip().startswith("- [")]
        non_entries = [l for l in lines if not l.strip().startswith("- [")]

        if len(entries) <= keep_recent:
            return 0

        # 保留最近 N 条
        kept = entries[-keep_recent:]
        old = entries[:-keep_recent]

        # 摘要旧条目
        summary = f"\n- [compacted] 已合并 {len(old)} 条旧记忆\n"
        for entry in old:
            clean = entry.strip().lstrip("- ")[:80]
            summary += f"  - {clean}\n"

        new_content = "\n".join(non_entries).rstrip() + "\n\n## 已压缩旧记忆\n" + summary + "\n## 近期记忆\n" + "\n".join(kept) + "\n"

        try:
            filepath.write_text(new_content, encoding="utf-8")
            self._cache["memory"] = new_content
            self._mtime[str(filepath)] = filepath.stat().st_mtime
            logger.info("记忆压缩完成: 保留 %d 条，移除 %d 条", keep_recent, len(old))
            return len(old)
        except Exception as e:
            logger.error("记忆压缩失败: %s", e)
            return 0

    def memory_hash(self) -> str:
        """计算 MEMORY.md 的内容哈希（用于变更检测）"""
        content = self.get_memory()
        return hashlib.md5(content.encode()).hexdigest()[:12]
