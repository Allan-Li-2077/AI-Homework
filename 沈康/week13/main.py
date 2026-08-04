"""
Harness 入口。
用法:
    python main.py             # 普通模式（INFO 日志）
    python main.py -v          # 调试模式（DEBUG 日志，可见每个 stage 的明细）
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from harness.cli import REPL


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,  # 日志走 stderr，不污染 stdout 上的用户输出
    )


def main() -> int:
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    setup_logging(verbose)
    root = Path(__file__).resolve().parent
    try:
        REPL(root).start()
    except RuntimeError as e:
        # 主要是 DASHSCOPE_API_KEY 缺失
        print(f"启动失败: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
