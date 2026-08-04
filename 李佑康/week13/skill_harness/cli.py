from __future__ import annotations

import argparse
import json
from pathlib import Path

from .harness import ProgressiveSkillHarness


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="渐进式 Skill 加载与执行 Harness")
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=Path(__file__).parents[1] / "skills",
        help="Skills 根目录",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="仅发现并列出 Skill 元数据")
    run = sub.add_parser("run", help="路由并执行一个 Skill")
    run.add_argument("request", help="用户请求")
    run.add_argument("--skill", help="跳过自动路由，指定 Skill 名称")
    run.add_argument("--trace", action="store_true", help="输出渐进式加载轨迹")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    harness = ProgressiveSkillHarness(args.skills_dir)
    if args.command == "list":
        for item in harness.list_skills():
            print(f"{item.name}\t{item.description}")
        return

    result = harness.run(args.request, args.skill)
    print(json.dumps(result.output, ensure_ascii=False, indent=2))
    if args.trace:
        print("\n加载轨迹:")
        for event in result.events:
            print(f"- {event.stage:17} [{event.skill or '-'}] {event.detail}")


if __name__ == "__main__":
    main()
