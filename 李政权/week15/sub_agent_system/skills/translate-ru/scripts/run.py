#!/usr/bin/env python3
"""独立子 Skill：translate-ru → 俄语"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.sub_agents.translate.lang_worker import cli_main

if __name__ == "__main__":
    raise SystemExit(cli_main("ru"))
