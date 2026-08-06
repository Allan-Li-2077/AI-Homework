"""
Skill 管理器：负责 Skill 文件的读取、创建、重写、局部修改和版本历史追踪。

设计（沿用 self_evolving_agent 参考项目的三层持久化）：
  - skills/{name}/SKILL.md            活动版本（永远只保留最新版），Agent 每次调用前读取
  - outputs/skill_versions/{name}_history.json  完整历史（含内容、时间、原因）
  - outputs/skill_snapshots/{name}_v{N}.md      每版独立 .md，方便 diff 或手工查看
版本号 = 历史条目数（v1 = 初始版本，每进化一次 +1）。

操作：
  - create   新建 Skill（写活动文件 + 存 v1 快照）
  - rewrite  整份替换（优化/进化 Agent 产出的完整新版，写活动文件 + 存新版本快照）
  - patch    局部替换（字符串精确替换，仅第一处，自动 bump 版本号）

加载：load_all()/get() 永远读 skills/ 下的最新版。
"""

import re
import json
from pathlib import Path
from datetime import datetime


class SkillManager:
    def __init__(self, skills_dir: str, versions_dir: str = "outputs/skill_versions"):
        self.skills_dir = Path(skills_dir)
        self.versions_dir = Path(versions_dir)
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir = Path(versions_dir).parent / "skill_snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    # ── 读取（永远读最新版） ─────────────────────────────────────────────────

    def load_all(self) -> dict[str, str]:
        """加载 skills/ 下所有 Skill 的最新版，返回 {skill_name: content}"""
        skills = {}
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    skills[skill_dir.name] = skill_file.read_text(encoding="utf-8")
        return skills

    def get(self, skill_name: str) -> str | None:
        skill_file = self.skills_dir / skill_name / "SKILL.md"
        if skill_file.exists():
            return skill_file.read_text(encoding="utf-8")
        return None

    # ── 写操作 ────────────────────────────────────────────────────────────────

    def create(self, skill_name: str, content: str, reason: str = "") -> bool:
        """创建新 Skill（对应 Hermes 的 skill_manage(action="create")）。"""
        skill_dir = self.skills_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            print(f"  [SkillManager] Skill '{skill_name}' 已存在，改用 rewrite/patch")
            return False
        skill_file.write_text(content, encoding="utf-8")
        self._save_version(skill_name, content, action="create", reason=reason)
        print(f"  [SkillManager] ✓ 创建 Skill: {skill_name}")
        return True

    def rewrite(self, skill_name: str, content: str, reason: str = "") -> bool:
        """整份替换 Skill 内容（优化 Agent 的完整新版），写活动文件并保存新版本。"""
        skill_dir = self.skills_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(self._bump_version(content), encoding="utf-8")
        self._save_version(skill_name, skill_file.read_text(encoding="utf-8"),
                           action="rewrite", reason=reason)
        print(f"  [SkillManager] ✓ 重写 Skill: {skill_name} (reason: {reason[:50]}...)")
        return True

    def patch(self, skill_name: str, old_text: str, new_text: str, reason: str = "") -> bool:
        """局部修改（字符串精确替换第一处），自动 bump 版本号。
        选择 replace 而非整份重写，是为了防止意外改动无关内容。"""
        skill_file = self.skills_dir / skill_name / "SKILL.md"
        if not skill_file.exists():
            print(f"  [SkillManager] ✗ Skill '{skill_name}' 不存在，无法 patch")
            return False
        content = skill_file.read_text(encoding="utf-8")
        if old_text not in content:
            print(f"  [SkillManager] ✗ 在 '{skill_name}' 中找不到目标文本")
            return False
        new_content = self._bump_version(content.replace(old_text, new_text, 1))
        skill_file.write_text(new_content, encoding="utf-8")
        self._save_version(skill_name, new_content, action="patch", reason=reason)
        print(f"  [SkillManager] ✓ 更新 Skill: {skill_name} (reason: {reason[:50]}...)")
        return True

    # ── 版本历史 ──────────────────────────────────────────────────────────────

    def get_version_history(self, skill_name: str) -> list[dict]:
        history_file = self.versions_dir / f"{skill_name}_history.json"
        if not history_file.exists():
            return []
        return json.loads(history_file.read_text(encoding="utf-8"))

    def get_all_version_summaries(self) -> dict[str, list]:
        summaries = {}
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                name = skill_dir.name
                history = self.get_version_history(name)
                summaries[name] = [
                    {"time": h["time"], "action": h["action"], "reason": h.get("reason", "")}
                    for h in history
                ]
        return summaries

    def get_active_versions(self) -> dict[str, int]:
        """当前 skills/ 下各 Skill 的版本号（= 历史条目数）。"""
        result = {}
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                name = skill_dir.name
                result[name] = len(self.get_version_history(name))
        return result

    def _save_version(self, skill_name: str, content: str, action: str, reason: str):
        history_file = self.versions_dir / f"{skill_name}_history.json"
        history = []
        if history_file.exists():
            history = json.loads(history_file.read_text(encoding="utf-8"))
        version_num = len(history) + 1
        history.append({
            "time": datetime.now().isoformat(),
            "action": action,
            "reason": reason,
            "version": version_num,
            "content": content,
            "snapshot_file": f"skill_snapshots/{skill_name}_v{version_num}.md",
        })
        history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshot_path = self.snapshots_dir / f"{skill_name}_v{version_num}.md"
        snapshot_path.write_text(
            f"<!-- {skill_name} v{version_num} | {action} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} -->\n"
            f"<!-- reason: {reason[:100]} -->\n\n{content}",
            encoding="utf-8",
        )

    @staticmethod
    def _bump_version(content: str) -> str:
        """将 SKILL.md frontmatter 中的 version 字段加 1。"""
        return re.sub(r"version:\s*(\d+)", lambda m: f"version: {int(m.group(1)) + 1}", content)
