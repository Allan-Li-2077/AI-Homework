# -*- coding: utf-8 -*-
"""
Skill 管理器：负责多文件 Skill（SKILL.md + reference/*.md）的读取、创建、
局部修改和版本历史追踪。

三重持久化设计：
  - skills/{name}/**/*.md                         活动版本，Agent 每次调用前读取
  - outputs/skill_versions/{name}_history.json    完整历史（每版含该skill下所有文件内容）
  - outputs/skill_snapshots/{name}_v{N}.md        每版一个合并快照文件（便于人工浏览diff）

版本号 = 历史条目数（v1 = 初始版本）。version 计数存在 SKILL.md 的 frontmatter
里，无论这一版改动的是 SKILL.md 本身还是某个 reference 文件，都会统一递增，
用于追踪整个 Skill（而不是单个文件）的自进化版本号。
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

    # ── 读取 ──────────────────────────────────────────────────────────────

    def load_all(self) -> dict[str, str]:
        """加载所有 Skill，返回 {skill_name: 拼接后的完整内容（SKILL.md + 所有reference文件）}"""
        skills = {}
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                merged = self._merged_content(skill_dir.name)
                if merged is not None:
                    skills[skill_dir.name] = merged
        return skills

    def get(self, skill_name: str) -> str | None:
        """返回某个 Skill 拼接后的完整内容（SKILL.md + reference/*.md）。"""
        return self._merged_content(skill_name)

    def get_file(self, skill_name: str, file: str = "SKILL.md") -> str | None:
        """返回某个 Skill 下单个文件的原始内容（供 Reviewer 精确定位 patch 目标）。"""
        target = self.skills_dir / skill_name / file
        if target.exists():
            return target.read_text(encoding="utf-8")
        return None

    def list_files(self, skill_name: str) -> list[str]:
        """列出某个 Skill 目录下所有 .md 文件的相对路径（SKILL.md 排最前）。"""
        skill_dir = self.skills_dir / skill_name
        if not skill_dir.is_dir():
            return []
        files = [f.relative_to(skill_dir).as_posix() for f in sorted(skill_dir.rglob("*.md"))]
        files.sort(key=lambda p: (p != "SKILL.md", p))
        return files

    def _merged_content(self, skill_name: str) -> str | None:
        skill_dir = self.skills_dir / skill_name
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            return None
        parts = [skill_file.read_text(encoding="utf-8")]
        ref_dir = skill_dir / "reference"
        if ref_dir.exists():
            for ref_file in sorted(ref_dir.glob("*.md")):
                rel = ref_file.relative_to(skill_dir).as_posix()
                parts.append(f"\n--- {rel} ---\n{ref_file.read_text(encoding='utf-8')}")
        return "\n".join(parts)

    # ── 写入 ──────────────────────────────────────────────────────────────

    def create(self, skill_name: str, content: str, reason: str = "", file: str = "SKILL.md") -> bool:
        """
        创建新文件。
          - file="SKILL.md"（默认）：创建全新 Skill 的入口文件
          - file="reference/xxx.md"：为已存在的 Skill 追加一个新的细节文件
            （此时 skill 的 SKILL.md 必须已存在，否则应先创建 SKILL.md）
        """
        skill_dir = self.skills_dir / skill_name
        target = skill_dir / file
        if target.exists():
            print(f"  [SkillManager] '{skill_name}/{file}' 已存在，改用 patch")
            return False
        if file != "SKILL.md" and not (skill_dir / "SKILL.md").exists():
            print(f"  [SkillManager] x Skill '{skill_name}' 尚无 SKILL.md，无法直接创建 {file}")
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if file != "SKILL.md":
            self._bump_skill_md_version(skill_name)
        self._save_version(skill_name, action="create", reason=reason, touched_file=file)
        print(f"  [SkillManager] + 创建: {skill_name}/{file}")
        return True

    def patch(self, skill_name: str, old_text: str, new_text: str, reason: str = "", file: str = "SKILL.md") -> bool:
        """局部修改某个文件（字符串精确替换，仅替换第一处），并递增 Skill 版本号。"""
        target = self.skills_dir / skill_name / file
        if not target.exists():
            print(f"  [SkillManager] x '{skill_name}/{file}' 不存在，无法 patch")
            return False
        content = target.read_text(encoding="utf-8")
        if old_text not in content:
            print(f"  [SkillManager] x 在 '{skill_name}/{file}' 中找不到目标文本")
            return False
        new_content = content.replace(old_text, new_text, 1)
        if file == "SKILL.md":
            new_content = self._bump_version_text(new_content)
        target.write_text(new_content, encoding="utf-8")
        if file != "SKILL.md":
            self._bump_skill_md_version(skill_name)
        self._save_version(skill_name, action="patch", reason=reason, touched_file=file)
        print(f"  [SkillManager] * 更新: {skill_name}/{file} (reason: {reason[:50]})")
        return True

    # ── 版本历史 ──────────────────────────────────────────────────────────

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
                    {"time": h["time"], "action": h["action"], "reason": h.get("reason", ""),
                     "file": h.get("touched_file", "SKILL.md")}
                    for h in history
                ]
        return summaries

    def get_active_versions(self) -> dict[str, int]:
        result = {}
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                name = skill_dir.name
                history = self.get_version_history(name)
                result[name] = len(history)
        return result

    def _save_version(self, skill_name: str, action: str, reason: str, touched_file: str = "SKILL.md"):
        history_file = self.versions_dir / f"{skill_name}_history.json"
        history = []
        if history_file.exists():
            history = json.loads(history_file.read_text(encoding="utf-8"))
        version_num = len(history) + 1
        files_now = self._collect_files(skill_name)
        history.append({
            "time": datetime.now().isoformat(),
            "action": action,
            "reason": reason,
            "touched_file": touched_file,
            "version": version_num,
            "files": files_now,
            "snapshot_file": f"skill_snapshots/{skill_name}_v{version_num}.md",
        })
        history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

        snapshot_path = self.snapshots_dir / f"{skill_name}_v{version_num}.md"
        snapshot_parts = [
            f"<!-- {skill_name} v{version_num} | {action} on {touched_file} | "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} -->",
            f"<!-- reason: {reason[:100]} -->",
            "",
        ]
        for rel_path, file_content in files_now.items():
            snapshot_parts.append(f"\n===== {rel_path} =====\n{file_content}")
        snapshot_path.write_text("\n".join(snapshot_parts), encoding="utf-8")

    def _collect_files(self, skill_name: str) -> dict[str, str]:
        skill_dir = self.skills_dir / skill_name
        files = {}
        for f in self.list_files(skill_name):
            files[f] = (skill_dir / f).read_text(encoding="utf-8")
        return files

    def _bump_version_text(self, content: str) -> str:
        def increment(m):
            return f"version: {int(m.group(1)) + 1}"
        return re.sub(r"version:\s*(\d+)", increment, content, count=1)

    def _bump_skill_md_version(self, skill_name: str):
        skill_file = self.skills_dir / skill_name / "SKILL.md"
        if skill_file.exists():
            content = skill_file.read_text(encoding="utf-8")
            skill_file.write_text(self._bump_version_text(content), encoding="utf-8")
