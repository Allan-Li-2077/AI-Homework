"""
Skill 执行器 — 对可执行 Skill 调用其 scripts/

当前内置：
  province-population-chart → scripts/generate_chart.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from src.skill_loader import SkillLoader, SKILLS_DIR

PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class SkillExecResult:
    skill: str
    ok: bool
    message: str
    output_path: str = ""
    province: str = ""
    summary: dict | None = None


def _load_province_data() -> dict:
    path = SKILLS_DIR / "province-population-chart" / "data.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}


def detect_province(text: str) -> str | None:
    data = _load_province_data()
    if not data:
        return None
    # 复用脚本里的提取逻辑
    script_dir = SKILLS_DIR / "province-population-chart" / "scripts"
    sys.path.insert(0, str(script_dir))
    try:
        from generate_chart import extract_province_from_text, load_data, DEFAULT_DATA
        return extract_province_from_text(text, load_data(DEFAULT_DATA))
    finally:
        if str(script_dir) in sys.path:
            sys.path.remove(str(script_dir))


def should_run_province_chart(message: str, activated_names: list[str]) -> str | None:
    """
    若应执行人口柱状图技能，返回省份名；否则 None。
    条件：技能已激活，或消息中明确出现已支持的省份名。
    """
    province = detect_province(message)
    if not province:
        return None
    if "province-population-chart" in activated_names:
        return province
    # 短消息几乎就是省名，或带有图表/人口意图
    compact = re.sub(r"\s+", "", message)
    chart_intent = any(
        k in message
        for k in ("人口", "柱状图", "统计图", "各地市", "地级市", "生成图", "画图", "图表")
    )
    aliases = [province, province + "省", province + "市"]
    almost_only_province = any(
        compact in {a, a + "的", "查" + a, a + "人口"} or compact == a
        for a in aliases
    )
    if chart_intent or almost_only_province or len(compact) <= len(province) + 4:
        return province
    return None


def run_province_population_chart(province: str) -> SkillExecResult:
    script = SKILLS_DIR / "province-population-chart" / "scripts" / "generate_chart.py"
    out_dir = PROJECT_ROOT / "outputs" / "charts"
    try:
        proc = subprocess.run(
            [sys.executable, str(script), province, "--out-dir", str(out_dir)],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            timeout=60,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except Exception as e:
        return SkillExecResult(
            skill="province-population-chart",
            ok=False,
            message=f"执行失败：{e}",
            province=province,
        )

    def _decode(b: bytes) -> str:
        if not b:
            return ""
        for enc in ("utf-8", "gbk", "cp936"):
            try:
                return b.decode(enc)
            except UnicodeDecodeError:
                continue
        return b.decode("utf-8", errors="replace")

    stdout = _decode(proc.stdout)
    stderr = _decode(proc.stderr)

    if proc.returncode != 0:
        err = (stderr or stdout or "").strip()
        return SkillExecResult(
            skill="province-population-chart",
            ok=False,
            message=err or "脚本返回非零退出码",
            province=province,
        )

    out_path = stdout.strip().splitlines()[-1] if stdout.strip() else ""
    # 兜底：按约定路径查找
    expected = out_dir / f"{province}.html"
    if (not out_path or not Path(out_path).exists()) and expected.exists():
        out_path = str(expected.resolve())

    summary = _summarize(province)
    rel = str(Path(out_path).resolve()) if out_path else str(expected)
    msg = f"已生成 {_display_name(province)} 各地市人口柱状图：{rel}"
    if summary:
        msg += (
            f"（{summary['count']} 个地市/区划，合计约 {summary['total']:.0f} 万人，"
            f"最高：{summary['top_name']} {summary['top_value']:g} 万人）"
        )
    return SkillExecResult(
        skill="province-population-chart",
        ok=True,
        message=msg,
        output_path=rel,
        province=province,
        summary=summary,
    )


def maybe_execute(message: str, activated_names: list[str]) -> SkillExecResult | None:
    province = should_run_province_chart(message, activated_names)
    if not province:
        return None
    # 确保技能被视为激活（即使只靠省名触发）
    return run_province_population_chart(province)


def _display_name(province: str) -> str:
    if province in ("北京", "上海", "天津", "重庆"):
        return province + "市"
    if province in ("内蒙古", "广西", "西藏", "宁夏", "新疆"):
        return province
    return province + "省"


def _summarize(province: str) -> dict | None:
    data = _load_province_data()
    cities = data.get(province)
    if not cities:
        return None
    items = [(n, float(v)) for n, v in cities.items() if float(v) > 0]
    if not items:
        return None
    items.sort(key=lambda x: x[1], reverse=True)
    return {
        "count": len(items),
        "total": sum(v for _, v in items),
        "top_name": items[0][0],
        "top_value": items[0][1],
    }


def list_supported_provinces() -> list[str]:
    return sorted(_load_province_data().keys())
