"""
主翻译 Skill 调用独立子 Skill（translate-en / ja / fr / ko / ru）。

调用约定：
  1. 用 SkillLoader 校验子 Skill 存在
  2. 优先进程内执行 lang_worker（同进程、可并行）
  3. 子 Skill 也可独立 CLI：python skills/translate-xx/scripts/run.py "…"
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from src.skill_loader import SKILLS_DIR, SkillLoader
from src.sub_agents.translate.lang_worker import SubAgentResult, translate_one
from src.sub_agents.translate.parse import CODE_TO_SKILL, LANGS

# 默认进程内调用；设 TRANSLATE_SUBSKILL_SUBPROCESS=1 则改为真正 subprocess 调脚本
USE_SUBPROCESS = os.getenv("TRANSLATE_SUBSKILL_SUBPROCESS", "0").strip().lower() in (
    "1", "true", "yes", "on",
)


def list_sub_skills() -> list[dict]:
    loader = SkillLoader()
    items = []
    for code, skill_name in CODE_TO_SKILL.items():
        meta = loader.get_skill(skill_name, load_body=False)
        label, lang_en = LANGS[code]
        items.append(
            {
                "code": code,
                "label": label,
                "lang_en": lang_en,
                "skill": skill_name,
                "agent": f"{skill_name}-agent",
                "installed": meta is not None,
                "path": str(meta.path) if meta else "",
            }
        )
    return items


def require_sub_skill(code: str) -> str:
    if code not in CODE_TO_SKILL:
        raise KeyError(f"未知语言代码: {code}")
    skill_name = CODE_TO_SKILL[code]
    meta = SkillLoader().get_skill(skill_name, load_body=False)
    if not meta:
        raise FileNotFoundError(
            f"主翻译 Skill 需要子 Skill `{skill_name}`，但未在 skills/ 找到"
        )
    return skill_name


def invoke_lang_skill(
    code: str,
    source: str,
    *,
    dry_run: bool = False,
) -> SubAgentResult:
    """主 Skill 调用指定语言的独立子 Skill。"""
    skill_name = require_sub_skill(code)
    if USE_SUBPROCESS:
        return _invoke_via_subprocess(skill_name, code, source, dry_run=dry_run)
    return translate_one(code, source, dry_run=dry_run, skill_name=skill_name)


def _invoke_via_subprocess(
    skill_name: str,
    code: str,
    source: str,
    *,
    dry_run: bool,
) -> SubAgentResult:
    script = SKILLS_DIR / skill_name / "scripts" / "run.py"
    if not script.exists():
        return SubAgentResult(
            agent=f"{skill_name}-agent",
            skill=skill_name,
            code=code,
            label=LANGS[code][0],
            ok=False,
            error=f"缺少脚本: {script}",
        )
    cmd = [sys.executable, str(script), source]
    if dry_run:
        cmd.append("--dry-run")
    project_root = SKILLS_DIR.parent
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            cwd=str(project_root),
            timeout=180,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except Exception as e:
        return SubAgentResult(
            agent=f"{skill_name}-agent",
            skill=skill_name,
            code=code,
            label=LANGS[code][0],
            ok=False,
            error=str(e),
        )
    out = (proc.stdout or b"").decode("utf-8", errors="replace")
    line = ""
    for raw in reversed(out.strip().splitlines() if out.strip() else []):
        if raw.strip().startswith("{"):
            line = raw.strip()
            break
    if not line:
        err = (proc.stderr or b"").decode("utf-8", errors="replace") or out
        return SubAgentResult(
            agent=f"{skill_name}-agent",
            skill=skill_name,
            code=code,
            label=LANGS[code][0],
            ok=False,
            error=err.strip() or "子 Skill 无 JSON 输出",
        )
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        return SubAgentResult(
            agent=f"{skill_name}-agent",
            skill=skill_name,
            code=code,
            label=LANGS[code][0],
            ok=False,
            error=f"JSON 解析失败: {e}",
        )
    return SubAgentResult(
        agent=data.get("agent") or f"{skill_name}-agent",
        skill=data.get("skill") or skill_name,
        code=data.get("code") or code,
        label=data.get("label") or LANGS[code][0],
        ok=bool(data.get("ok")),
        text=data.get("text") or "",
        error=data.get("error") or "",
        metrics=data.get("metrics") or {},
        elapsed_s=float(data.get("elapsed_s") or 0),
    )


# 兼容旧 import
def get_sub_agent(code: str):
    """返回可 .run(source) 的轻量代理，内部转调 invoke_lang_skill。"""

    class _Proxy:
        def __init__(self, c: str):
            self.code = c
            self.skill = CODE_TO_SKILL[c]
            self.label = LANGS[c][0]
            self.lang_en = LANGS[c][1]
            self.agent_name = f"{self.skill}-agent"

        def run(self, source: str, *, dry_run: bool = False) -> SubAgentResult:
            return invoke_lang_skill(self.code, source, dry_run=dry_run)

    return _Proxy(code)


def list_sub_agents() -> list[dict]:
    return list_sub_skills()
