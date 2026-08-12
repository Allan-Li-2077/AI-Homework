"""
Skill 执行器 — 对可执行 Skill 调用其 scripts/

当前内置：
  province-population-chart → scripts/generate_chart.py
  yijing-sizhu-gua → scripts/generate_fortune.py
  yijing-sizhu-gua1 → scripts/generate_fortune_llm_html.py（LLM 生成 HTML）
  multi-lang-translate → scripts/translate.py
    （主 Skill 分发；调用 translate-en/ja/fr/ko/ru 五个独立子 Skill；可并行/串行）
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


def _decode(b: bytes) -> str:
    if not b:
        return ""
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


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
    script_dir = SKILLS_DIR / "province-population-chart" / "scripts"
    sys.path.insert(0, str(script_dir))
    try:
        from generate_chart import extract_province_from_text, load_data, DEFAULT_DATA
        return extract_province_from_text(text, load_data(DEFAULT_DATA))
    finally:
        if str(script_dir) in sys.path:
            sys.path.remove(str(script_dir))


def should_run_province_chart(message: str, activated_names: list[str]) -> str | None:
    province = detect_province(message)
    if not province:
        return None
    if "province-population-chart" in activated_names:
        return province
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


# ── 易经四柱起卦 ──────────────────────────────────────────────────────────────

def _yijing_helpers():
    script_dir = SKILLS_DIR / "yijing-sizhu-gua" / "scripts"
    sys.path.insert(0, str(script_dir))
    try:
        from generate_fortune import has_fortune_intent, parse_fortune_query
        return has_fortune_intent, parse_fortune_query
    finally:
        if str(script_dir) in sys.path:
            sys.path.remove(str(script_dir))


def detect_yijing_intent(text: str) -> bool:
    try:
        has_fortune_intent, _ = _yijing_helpers()
        return has_fortune_intent(text)
    except Exception:
        keys = ("算命", "易经", "排盘", "本命卦", "起卦", "推命", "看运势")
        return any(k in text for k in keys)


def should_run_yijing(message: str, activated_names: list[str]) -> bool:
    if "yijing-sizhu-gua" in activated_names or "yijing-sizhu-gua1" in activated_names:
        return True
    return detect_yijing_intent(message)


def detect_yijing1_intent(text: str) -> bool:
    """显式要求 LLM-HTML 版，或点名 gua1。"""
    if re.search(r"yijing-sizhu-gua1", text, re.IGNORECASE):
        return True
    keys = (
        "LLM生成运势页",
        "用大模型生成算命",
        "LLM生成算命HTML",
        "llm生成运势",
        "模型生成HTML",
    )
    return any(k in text for k in keys)


def run_yijing_sizhu_gua1(message: str) -> SkillExecResult:
    script = SKILLS_DIR / "yijing-sizhu-gua1" / "scripts" / "generate_fortune_llm_html.py"
    out_dir = PROJECT_ROOT / "outputs" / "fortune1"
    try:
        _, parse_fortune_query = _yijing_helpers()
        cleaned = re.sub(
            r"(?:/skill\s+|@skill\s+|@)yijing-sizhu-gua1\b",
            " ",
            message,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if "算命" not in cleaned and "排盘" not in cleaned:
            cleaned = "算命：" + cleaned
        info = parse_fortune_query(cleaned)
        if info.get("missing"):
            return SkillExecResult(
                skill="yijing-sizhu-gua1",
                ok=False,
                message=(
                    "算命信息不完整，请补充："
                    + "、".join(info["missing"])
                    + "。示例：@yijing-sizhu-gua1 算命：李明，男，1990-08-15，辰时"
                ),
                summary={"missing": info["missing"]},
            )
    except Exception as e:
        return SkillExecResult(
            skill="yijing-sizhu-gua1",
            ok=False,
            message=f"解析生辰失败：{e}",
        )

    try:
        proc = subprocess.run(
            [sys.executable, str(script), message, "--out-dir", str(out_dir)],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            timeout=180,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except Exception as e:
        return SkillExecResult(
            skill="yijing-sizhu-gua1",
            ok=False,
            message=f"执行失败：{e}",
        )

    stdout = _decode(proc.stdout)
    stderr = _decode(proc.stderr)
    line = ""
    for raw in reversed(stdout.strip().splitlines() if stdout.strip() else []):
        if raw.strip().startswith("{"):
            line = raw.strip()
            break

    payload: dict = {}
    if line:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {}

    if proc.returncode != 0 or not payload.get("ok"):
        err = payload.get("error") or (stderr or stdout or "").strip()
        return SkillExecResult(
            skill="yijing-sizhu-gua1",
            ok=False,
            message=err or "脚本返回非零退出码",
            summary=payload if payload else None,
        )

    metrics = payload.get("metrics") or {}
    out_path = payload.get("output_path") or ""
    summary = payload.get("summary") or {}
    summary["metrics"] = metrics
    fname = Path(out_path).name if out_path else ""
    fb = "回落模板" if metrics.get("fallback") else "LLM-HTML"
    msg = (
        f"已生成运势页（{fb}）：{out_path}"
        f"（本卦 {summary.get('ben_gua', '?')} → 变卦 {summary.get('bian_gua', '?')}；"
        f"用时 {metrics.get('elapsed_s', '?')}s，"
        f"Token {metrics.get('total_tokens', 0)}"
        f"（prompt {metrics.get('prompt_tokens', 0)} + "
        f"completion {metrics.get('completion_tokens', 0)}））"
    )
    if fname:
        msg += f"。Web 可打开 /fortune1/{fname}"
    return SkillExecResult(
        skill="yijing-sizhu-gua1",
        ok=True,
        message=msg,
        output_path=out_path,
        summary=summary,
    )


def run_yijing_sizhu_gua(message: str) -> SkillExecResult:
    script = SKILLS_DIR / "yijing-sizhu-gua" / "scripts" / "generate_fortune.py"
    out_dir = PROJECT_ROOT / "outputs" / "fortune"
    try:
        has_fortune_intent, parse_fortune_query = _yijing_helpers()
        info = parse_fortune_query(message)
        if info.get("missing"):
            return SkillExecResult(
                skill="yijing-sizhu-gua",
                ok=False,
                message=(
                    "算命信息不完整，请补充："
                    + "、".join(info["missing"])
                    + "。示例：算命：李明，男，1990-08-15，辰时"
                ),
                summary={"missing": info["missing"]},
            )
    except Exception as e:
        return SkillExecResult(
            skill="yijing-sizhu-gua",
            ok=False,
            message=f"解析生辰失败：{e}",
        )

    try:
        proc = subprocess.run(
            [sys.executable, str(script), message, "--out-dir", str(out_dir)],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except Exception as e:
        return SkillExecResult(
            skill="yijing-sizhu-gua",
            ok=False,
            message=f"执行失败：{e}",
        )

    stdout = _decode(proc.stdout)
    stderr = _decode(proc.stderr)
    line = ""
    for raw in reversed(stdout.strip().splitlines() if stdout.strip() else []):
        if raw.strip().startswith("{"):
            line = raw.strip()
            break

    payload: dict = {}
    if line:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {}

    if proc.returncode != 0 or not payload.get("ok"):
        err = payload.get("error") or (stderr or stdout or "").strip()
        return SkillExecResult(
            skill="yijing-sizhu-gua",
            ok=False,
            message=err or "脚本返回非零退出码",
            summary=payload if payload else None,
        )

    metrics = payload.get("metrics") or {}
    out_path = payload.get("output_path") or ""
    summary = payload.get("summary") or {}
    summary["metrics"] = metrics
    fname = Path(out_path).name if out_path else ""
    msg = (
        f"已动态生成运势页：{out_path}"
        f"（本卦 {summary.get('ben_gua', '?')} → 变卦 {summary.get('bian_gua', '?')}；"
        f"用时 {metrics.get('elapsed_s', '?')}s，"
        f"Token {metrics.get('total_tokens', 0)}"
        f"（prompt {metrics.get('prompt_tokens', 0)} + "
        f"completion {metrics.get('completion_tokens', 0)}））"
    )
    if fname:
        msg += f"。Web 可打开 /fortune/{fname}"
    return SkillExecResult(
        skill="yijing-sizhu-gua",
        ok=True,
        message=msg,
        output_path=out_path,
        summary=summary,
    )


# ── 多语言翻译（主 agent + 五语言子 agent）────────────────────────────────────

def _translate_helpers():
    from src.sub_agents.translate import (
        detect_targets,
        has_translate_intent,
        parse_query,
    )
    return detect_targets, has_translate_intent, parse_query


def detect_translate_intent(text: str) -> bool:
    """有翻译意图，且提到了支持或不支持的目标语言时触发。"""
    try:
        _, has_translate_intent, parse_query = _translate_helpers()
        if not has_translate_intent(text):
            return False
        parsed = parse_query(text)
        return bool(parsed.get("targets") or parsed.get("unsupported"))
    except Exception:
        keys = ("翻译", "译成", "翻成", "translate")
        langs = (
            "英文", "英语", "日文", "日语", "法语", "法文", "韩语", "韩文", "俄语", "俄文",
            "德语", "汉语", "中文", "西班牙语", "意大利语",
        )
        return any(k in text for k in keys) and any(l in text for l in langs)


def should_run_translate(message: str, activated_names: list[str]) -> bool:
    if "multi-lang-translate" in activated_names:
        return True
    return detect_translate_intent(message)


def run_multi_lang_translate(message: str) -> SkillExecResult:
    """在服务进程内直接跑主 Agent，避免子进程丢开关 / 参数解析问题。"""
    from src.sub_agents.translate.config import describe_mode, get_parallel_enabled
    from src.sub_agents.translate.format_reply import format_translation_reply
    from src.sub_agents.translate.main_agent import TranslateMainAgent

    parallel = get_parallel_enabled()
    try:
        payload = TranslateMainAgent().run(message, parallel=parallel, dry_run=False)
    except Exception as e:
        return SkillExecResult(
            skill="multi-lang-translate",
            ok=False,
            message=f"执行失败：{e}",
            summary={"mode": "parallel" if parallel else "serial", "switch": describe_mode()},
        )

    # 强制写入本次实际模式，防止展示与执行不一致
    payload["parallel"] = parallel
    payload["mode"] = "parallel" if parallel else "serial"
    if isinstance(payload.get("metrics"), dict):
        payload["metrics"]["mode"] = payload["mode"]
    payload["switch"] = describe_mode()
    payload["display"] = format_translation_reply(payload)

    if payload.get("error") == "抱歉，不支持翻译该种语言" and not (payload.get("targets") or []):
        return SkillExecResult(
            skill="multi-lang-translate",
            ok=False,
            message="抱歉，不支持翻译该种语言",
            summary=payload,
        )

    display = (payload.get("display") or "").strip() or format_translation_reply(payload)
    if not payload.get("ok"):
        return SkillExecResult(
            skill="multi-lang-translate",
            ok=False,
            message=display or (payload.get("error") or "翻译失败"),
            summary=payload,
        )

    summary = {
        "source": payload.get("source"),
        "targets": payload.get("targets"),
        "translations": payload.get("translations") or {},
        "metrics": payload.get("metrics") or {},
        "mode": payload.get("mode"),
        "parallel": parallel,
        "switch": payload.get("switch"),
        "sub_agent_runs": payload.get("sub_skill_runs") or payload.get("sub_agent_runs") or [],
        "sub_skill_runs": payload.get("sub_skill_runs") or payload.get("sub_agent_runs") or [],
        "main_agent": payload.get("main_agent"),
        "unsupported": payload.get("unsupported") or [],
        "display": display,
    }
    return SkillExecResult(
        skill="multi-lang-translate",
        ok=True,
        message=display,
        summary=summary,
    )


def maybe_execute(message: str, activated_names: list[str]) -> SkillExecResult | None:
    # 多语言翻译（意图明确时优先，避免被其它技能抢占）
    if should_run_translate(message, activated_names):
        return run_multi_lang_translate(message)

    # LLM-HTML 版优先（显式激活或点名 gua1）
    if "yijing-sizhu-gua1" in activated_names or detect_yijing1_intent(message):
        return run_yijing_sizhu_gua1(message)

    # 原版模板 HTML（LLM 只写解读正文）
    if should_run_yijing(message, activated_names):
        if "yijing-sizhu-gua" in activated_names or detect_yijing_intent(message):
            return run_yijing_sizhu_gua(message)

    province = should_run_province_chart(message, activated_names)
    if province:
        return run_province_population_chart(province)
    return None


def reply_hint_for_exec(result: SkillExecResult) -> str:
    """拼进 system prompt 的简短回复指引。"""
    if result.skill == "multi-lang-translate":
        if result.message.strip() == "抱歉，不支持翻译该种语言":
            return (
                "请原样回复用户下面这一行，不要增删改字：\n"
                "抱歉，不支持翻译该种语言"
            )
        return (
            "请原样输出 Skill 执行结果中的文案"
            "（开头为「并行模式」或「串行模式」，"
            "每种语言为「英文：\\n译文」格式，"
            "末尾为「用时 Xs，Token N」）；"
            "不要改写、不要增删段落，不要重新翻译。"
        )
    if result.skill in ("yijing-sizhu-gua", "yijing-sizhu-gua1"):
        return (
            "请根据执行结果简洁回复：告知 HTML 路径与本卦/变卦要点，"
            "并说明本次 Skill 用时与 Token；不要输出 HTML 源码；"
            "不要假装还需要再生成一次。"
        )
    if result.skill == "province-population-chart":
        return (
            "请根据执行结果简洁回复用户：告知文件路径与人口要点；"
            "不要输出 HTML 源码；不要假装还需要再生成一次。"
        )
    return "请根据 Skill 执行结果简洁回复用户，不要输出源码。"


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
