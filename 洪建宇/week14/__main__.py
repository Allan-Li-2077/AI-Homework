"""天气查询 CLI 入口。

用法示例：
    python -m weather_query 北京
    python -m weather_query 上海 --format json
    python -m weather_query "广州天河区"
    python -m weather_query Tokyo
"""

from __future__ import annotations

import argparse
import sys

from . import WeatherService, QueryError, format_weather


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="weather-query",
        description="查询指定地点的当前天气（基于 wttr.in，备用 Open-Meteo）",
    )
    parser.add_argument(
        "location",
        help="要查询的地点，支持中文名（北京）、英文名（Tokyo）、拼音（shanghai）",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["text", "json"],
        default="text",
        help="输出格式：text（默认，人类可读）/ json（程序解析）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    service = WeatherService()
    try:
        result = service.query(args.location)
    except QueryError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    print(format_weather(result, fmt=args.format))
    return 0


if __name__ == "__main__":
    sys.exit(main())
