from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .errors import HarnessError
from .executor import SkillExecutor
from .session import ProgressiveSkillHarness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Progressive SKILL.md loading/execution harness")
    parser.add_argument("--skills-dir", action="append", help="Skill directory. Repeatable. Default: ./skills then ./.cursor/skills")
    parser.add_argument("--cwd", default=None, help="Project working directory. Default: current directory")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List skills using front matter only")
    p_list.add_argument("--json", action="store_true")
    p_list.add_argument("--trace", action="store_true")

    p_route = sub.add_parser("route", help="Route a request using metadata only")
    p_route.add_argument("request")
    p_route.add_argument("--json", action="store_true")
    p_route.add_argument("--trace", action="store_true")

    p_context = sub.add_parser("context", help="Build selected skill context progressively")
    p_context.add_argument("request")
    p_context.add_argument("--skill", help="Explicit skill name")
    p_context.add_argument("--resources", choices=["none", "auto", "all"], default="auto")
    p_context.add_argument("--max-resource-chars", type=int, default=None)
    p_context.add_argument("--include-content", action="store_true", help="Include markdown/resource content in JSON output")
    p_context.add_argument("--json", action="store_true")
    p_context.add_argument("--trace", action="store_true")

    p_run = sub.add_parser("run", help="Build context and execute a known skill adapter")
    p_run.add_argument("request")
    p_run.add_argument("--skill", help="Explicit skill name")
    p_run.add_argument("--resources", choices=["none", "auto", "all"], default="auto")
    p_run.add_argument("--output", "-o", help="Output path for adapters that support it")
    p_run.add_argument("--input", dest="input_path", help="Input notes file for adapters that support it")
    p_run.add_argument("--title", help="Optional page title for html-page adapter")
    p_run.add_argument("--word", help="Explicit word for flash-card adapter")
    p_run.add_argument("--svg", help="SVG path for baoyu-diagram converter adapter")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--json", action="store_true")
    p_run.add_argument("--trace", action="store_true")

    args = parser.parse_args(argv)
    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd().resolve()
    skill_dirs = [Path(p) for p in args.skills_dir] if args.skills_dir else None
    harness = ProgressiveSkillHarness(skill_dirs, cwd=cwd)

    try:
        if args.command == "list":
            skills = harness.discover()
            if args.json:
                _print_json({"skills": [s.to_dict() for s in skills], "trace": _trace(harness, args.trace)})
            else:
                for s in skills:
                    version = f" v{s.version}" if s.version else ""
                    print(f"- {s.name}{version}: {s.description[:100]}")
                _print_trace(harness, args.trace)
            return 0

        if args.command == "route":
            candidates = harness.route(args.request)
            if args.json:
                _print_json({"candidates": [c.to_dict() for c in candidates], "trace": _trace(harness, args.trace)})
            else:
                for c in candidates:
                    print(f"{c.skill.name}\t score={c.score}\t reasons={', '.join(c.reasons)}")
                _print_trace(harness, args.trace)
            return 0

        if args.command == "context":
            context = harness.build_context(
                args.request,
                explicit_skill=args.skill,
                resource_mode=args.resources,
                max_resource_chars=args.max_resource_chars,
            )
            if args.json:
                skill = context["skill"]
                payload = {
                    "request": context["request"],
                    "selected": context["selected"],
                    "skill": skill.to_dict(include_markdown=args.include_content),
                    "resources": [r.to_dict(include_content=args.include_content) for r in context["resources"]],
                    "available_paths": context["available_paths"],
                    "trace": _trace(harness, args.trace),
                }
                _print_json(payload)
            else:
                skill = context["skill"]
                print(f"selected: {skill.meta.name}")
                print(f"loaded SKILL.md chars: {len(skill.markdown)}")
                if context["resources"]:
                    print("loaded resources:")
                    for resource in context["resources"]:
                        print(f"- {resource.relative_path} ({len(resource.content)} chars)")
                else:
                    print("loaded resources: none")
                _print_trace(harness, args.trace)
            return 0

        if args.command == "run":
            result = SkillExecutor(harness).run(
                args.request,
                explicit_skill=args.skill,
                resource_mode=args.resources,
                output=args.output,
                input_path=args.input_path,
                title=args.title,
                word=args.word,
                svg=args.svg,
                dry_run=args.dry_run,
            )
            if args.json:
                payload = result.to_dict()
                if not args.trace:
                    payload.pop("trace", None)
                _print_json(payload)
            else:
                print(f"skill: {result.skill}")
                print(f"returncode: {result.returncode}")
                if result.command:
                    print("command: " + " ".join(result.command))
                if result.stdout.strip():
                    print("stdout:\n" + result.stdout.strip())
                if result.stderr.strip():
                    print("stderr:\n" + result.stderr.strip())
                if result.outputs:
                    print("outputs:")
                    for output in result.outputs:
                        print(f"- {output}")
                _print_trace(harness, args.trace)
            return result.returncode

    except HarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        _print_trace(harness, getattr(args, "trace", False), stream=sys.stderr)
        return 2
    return 1


def _trace(harness: ProgressiveSkillHarness, enabled: bool):
    return [e.to_dict() for e in harness.trace] if enabled else []


def _print_trace(harness: ProgressiveSkillHarness, enabled: bool, *, stream=None) -> None:
    if not enabled:
        return
    stream = stream or sys.stdout
    print("\ntrace:", file=stream)
    for event in harness.trace:
        suffix = f" [{event.bytes} bytes]" if event.bytes is not None else ""
        path = f" @ {event.path}" if event.path else ""
        print(f"- {event.phase}: {event.detail}{path}{suffix}", file=stream)


def _print_json(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
