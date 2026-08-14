"""
单语种翻译 Worker：供独立子 Skill（translate-en 等）与主 Skill 调用。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.sub_agents.translate.parse import CODE_TO_SKILL, LANGS


@dataclass
class SubAgentResult:
    agent: str
    skill: str
    code: str
    label: str
    ok: bool
    text: str = ""
    error: str = ""
    metrics: dict = field(default_factory=dict)
    elapsed_s: float = 0.0


def _count_scripts(text: str) -> dict[str, int]:
    return {
        "cjk": len(re.findall(r"[\u4e00-\u9fff]", text)),
        "latin": len(re.findall(r"[A-Za-zÀ-ÿŒœ]", text)),
        "cyrillic": len(re.findall(r"[А-Яа-яЁё]", text)),
        "kana": len(re.findall(r"[\u3040-\u30ff]", text)),
        "hangul": len(re.findall(r"[\uac00-\ud7af]", text)),
    }


def _looks_like_target(code: str, text: str) -> bool:
    if not text or not text.strip():
        return False
    s = _count_scripts(text)
    if code == "ko":
        return s["hangul"] > 0 and s["hangul"] >= max(s["cjk"], 1) * 0.5
    if code == "ru":
        return s["cyrillic"] > 0 and s["cyrillic"] >= s["cjk"]
    if code == "ja":
        if s["kana"] > 0:
            return True
        return s["cjk"] > 0 and s["latin"] == 0
    # en / fr
    if s["cjk"] == 0 and s["hangul"] == 0:
        return s["latin"] > 0
    return s["latin"] >= s["cjk"] * 2


def translate_one(
    code: str,
    source: str,
    *,
    dry_run: bool = False,
    skill_name: str | None = None,
) -> SubAgentResult:
    if code not in LANGS:
        raise KeyError(f"未知语言代码: {code}")
    label, lang_en = LANGS[code]
    skill = skill_name or CODE_TO_SKILL[code]
    agent_name = f"{skill}-agent"
    t0 = time.time()

    if dry_run:
        return SubAgentResult(
            agent=agent_name,
            skill=skill,
            code=code,
            label=label,
            ok=True,
            text=f"[dry-run → {label}] {source}",
            elapsed_s=round(time.time() - t0, 3),
            metrics={"dry_run": True, "skill": skill},
        )

    try:
        text, metrics = _llm_translate(code, label, lang_en, agent_name, source, retry=False)
        if not _looks_like_target(code, text):
            text2, metrics2 = _llm_translate(
                code, label, lang_en, agent_name, source, retry=True
            )
            metrics = {
                "prompt_tokens": metrics.get("prompt_tokens", 0)
                + metrics2.get("prompt_tokens", 0),
                "completion_tokens": metrics.get("completion_tokens", 0)
                + metrics2.get("completion_tokens", 0),
                "total_tokens": metrics.get("total_tokens", 0)
                + metrics2.get("total_tokens", 0),
                "model": metrics2.get("model") or metrics.get("model"),
                "agent": agent_name,
                "skill": skill,
                "retried": True,
            }
            text = text2
        else:
            metrics["skill"] = skill
        return SubAgentResult(
            agent=agent_name,
            skill=skill,
            code=code,
            label=label,
            ok=True,
            text=text,
            elapsed_s=round(time.time() - t0, 3),
            metrics=metrics,
        )
    except Exception as e:
        return SubAgentResult(
            agent=agent_name,
            skill=skill,
            code=code,
            label=label,
            ok=False,
            error=str(e),
            elapsed_s=round(time.time() - t0, 3),
            metrics={"skill": skill},
        )


def _llm_translate(
    code: str,
    label: str,
    lang_en: str,
    agent_name: str,
    source: str,
    *,
    retry: bool,
) -> tuple[str, dict]:
    from src.llm_config import get_chat_client

    client, model = get_chat_client()
    system = (
        f"You are a professional translator sub-skill agent ({agent_name}). "
        f"Your ONLY job is to translate Chinese into {lang_en} ({label}). "
        f"The entire output MUST be written in {lang_en}. "
        f"Do NOT output Chinese. Do NOT transliterate into Chinese. "
        f"Do NOT add titles, labels, quotes, or explanations — translation text only."
    )
    if code == "ko":
        system += " Prefer natural Hangul; keep Chinese proper nouns only when necessary."
    if retry:
        system += (
            f" CRITICAL RETRY: previous attempt wrongly used Chinese. "
            f"Now output fluent {lang_en} only, with zero Chinese characters "
            f"(except unavoidable proper nouns)."
        )
    user = (
        f"[TARGET_LANGUAGE={lang_en}]\n"
        f"[OUTPUT_LANGUAGE={lang_en}]\n"
        f"---\n{source}"
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
    )
    raw = (resp.choices[0].message.content or "").strip()
    raw = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", raw).strip()
    raw = re.sub(
        rf"^(?:{re.escape(label)}|{re.escape(lang_en)})\s*[:：]\s*",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()
    usage = getattr(resp, "usage", None)
    metrics = {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        "model": model,
        "agent": agent_name,
    }
    if not raw:
        raise ValueError(f"{agent_name} 返回空译文")
    return raw, metrics


def cli_main(code: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"translate-{code} 子 Skill")
    parser.add_argument("text", nargs="?", default="", help="待译中文")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    text = args.text.strip()
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    if not text:
        print(json.dumps({"ok": False, "error": "缺少待译文本", "code": code}, ensure_ascii=False))
        return 1
    result = translate_one(code, text, dry_run=args.dry_run)
    print(json.dumps(asdict(result), ensure_ascii=False))
    return 0 if result.ok else 1
