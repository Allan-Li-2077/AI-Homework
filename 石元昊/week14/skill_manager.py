"""
Skill 版本管理器：负责 Skill 文件的读写、版本快照和差异追踪。

设计思路：
  - skills/{name}/SKILL.md   → 活动版本（Agent 每次调用前读取）
  - outputs/snapshots/       → 每个版本独立 .md 快照
  - outputs/history.json     → 全量版本历史（含内容、时间、原因、指标）

与参考项目的差异：
  - 使用单一 history.json 管理所有 Skill 的版本历史（而非每个 Skill 独立 JSON）
  - 每次版本记录附带 skill_char_count 指标（文档字符数），方便观察优化效果
"""

import re
import json
import shutil
from pathlib import Path
from datetime import datetime


class SkillManager:

    def __init__(self, skills_dir: str, outputs_dir: str = "outputs"):
        self.skills_dir = Path(skills_dir)
        self.outputs_dir = Path(outputs_dir)
        self.snapshots_dir = self.outputs_dir / "snapshots"
        self.history_file = self.outputs_dir / "history.json"
        # 确保目录存在
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    # ── 读取 ─────────────────────────────────────────────────────

    def load_all(self) -> dict:
        """加载全部 Skill，返回 {name: content}"""
        result = {}
        if not self.skills_dir.exists():
            return result
        for d in self.skills_dir.iterdir():
            if d.is_dir():
                f = d / "SKILL.md"
                if f.exists():
                    result[d.name] = f.read_text(encoding="utf-8")
        return result

    def get(self, name: str) -> str | None:
        """读取指定 Skill 内容，不存在返回 None"""
        f = self.skills_dir / name / "SKILL.md"
        return f.read_text(encoding="utf-8") if f.exists() else None

    # ── 写入 ─────────────────────────────────────────────────────

    def save(self, name: str, content: str, reason: str = "") -> int:
        """
        保存 Skill 内容到磁盘，同时记录版本快照。
        返回新版本号。
        """
        # 写活动版本
        skill_dir = self.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        # 记录版本
        history = self._load_history()
        version = len([h for h in history if h["name"] == name]) + 1
        history.append({
            "name": name,
            "version": version,
            "action": "save",
            "reason": reason,
            "time": datetime.now().isoformat(),
            "char_count": len(content),
        })
        self._save_history(history)

        # 保存快照文件
        snap = self.snapshots_dir / f"{name}_v{version}.md"
        snap.write_text(
            f"<!-- v{version} | {reason[:100]} | "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} -->\n\n{content}",
            encoding="utf-8",
        )
        return version

    # ── 备份 / 还原 ──────────────────────────────────────────────

    def backup(self) -> Path:
        """备份当前 skills/ 到 outputs/skills_backup/，返回备份路径"""
        backup_dir = self.outputs_dir / "skills_backup"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(self.skills_dir, backup_dir)
        return backup_dir

    def restore(self, backup_dir: str | Path = None) -> None:
        """从备份还原 skills/，并清空版本历史"""
        backup_dir = Path(backup_dir) if backup_dir else self.outputs_dir / "skills_backup"
        if not backup_dir.exists():
            raise FileNotFoundError(f"备份目录不存在: {backup_dir}")
        if self.skills_dir.exists():
            shutil.rmtree(self.skills_dir)
        shutil.copytree(backup_dir, self.skills_dir)
        # 清空历史记录和快照
        if self.history_file.exists():
            self.history_file.unlink()
        if self.snapshots_dir.exists():
            shutil.rmtree(self.snapshots_dir)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    # ── 查询 ─────────────────────────────────────────────────────

    def get_history(self, name: str = None) -> list:
        """获取版本历史。name=None 返回全部，否则只返回指定 Skill 的。"""
        history = self._load_history()
        if name:
            return [h for h in history if h["name"] == name]
        return history

    def get_active_char_counts(self) -> dict:
        """返回每个 Skill 当前的字符数"""
        return {name: len(content) for name, content in self.load_all().items()}

    # ── 内部方法 ──────────────────────────────────────────────────

    def _load_history(self) -> list:
        if self.history_file.exists():
            return json.loads(self.history_file.read_text(encoding="utf-8"))
        return []

    def _save_history(self, history: list):
        self.history_file.write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
        )
