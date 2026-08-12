#!/usr/bin/env python3
"""
多语言翻译 CLI — 委托给 TranslateMainAgent（主 agent + 五语言子 agent）。

用法：
  python translate.py "请翻译成英文：今天天气很好"
  python translate.py "翻译成德文：你好" --dry-run
  python translate.py "翻译英文日文：春天" --serial
  python translate.py "翻译英文日文：春天" --parallel
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

SKILL_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SKILL_DIR.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.sub_agents.translate import (  # noqa: E402
    TranslateMainAgent,
)
from src.sub_agents.translate.parse import UNSUPPORTED_MSG  # noqa: E402
from src.sub_agents.translate.format_reply import format_translation_reply  # noqa: E402


def translate(
    text: str,
    *,
    dry_run: bool = False,
    parallel: bool | None = None,
) -> dict:
    return TranslateMainAgent().run(text, dry_run=dry_run, parallel=parallel)


def format_human(result: dict) -> str:
    return format_translation_reply(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="多语言翻译主 agent CLI")
    parser.add_argument("text", nargs="?", default="", help="用户输入原文")
    parser.add_argument("--dry-run", action="store_true", help="只解析/分发，不调 LLM")
    parser.add_argument("--parallel", action="store_true", help="强制并行执行子 agent")
    parser.add_argument("--serial", action="store_true", help="强制串行执行子 agent")
    args = parser.parse_args(argv)

    text = args.text.strip()
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    if not text:
        payload = {"ok": False, "error": "缺少待处理文本", "display": "缺少待处理文本"}
        print(json.dumps(payload, ensure_ascii=False))
        return 1

    parallel = None
    if args.parallel:
        parallel = True
    elif args.serial:
        parallel = False

    result = translate(text, dry_run=args.dry_run, parallel=parallel)
    result["display"] = format_translation_reply(result)
    print(json.dumps(result, ensure_ascii=False))
    if result.get("error") == UNSUPPORTED_MSG and not (result.get("targets") or []):
        return 2
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
