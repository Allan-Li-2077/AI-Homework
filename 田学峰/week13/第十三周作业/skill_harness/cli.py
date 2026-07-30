from __future__ import annotations

import argparse
import json
from pathlib import Path

from .loader import ProgressiveLoader
from .matcher import SkillMatcher
from .models import MatchResult
from .registry import SkillRegistry
from .runners import RunnerRegistry


DEFAULT_SKILLS_DIR = Path("skills")


def main() -> None:
    parser = argparse.ArgumentParser(description="渐进式加载并执行 Skills 的 harness")
    parser.add_argument("--skills-dir", default=str(DEFAULT_SKILLS_DIR), help="包含 */SKILL.md 的目录")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="只读取元数据，列出可用 skills")

    match_parser = sub.add_parser("match", help="根据用户请求给 skills 排名")
    match_parser.add_argument("request")
    match_parser.add_argument("--top-k", type=int, default=3)

    inspect_parser = sub.add_parser("inspect", help="加载一个完整 skill，并按需加载引用文件")
    inspect_parser.add_argument("skill")
    inspect_parser.add_argument("--request", default="")
    inspect_parser.add_argument("--load-all-refs", action="store_true")

    run_parser = sub.add_parser("run", help="匹配、渐进式加载并执行 skill")
    run_parser.add_argument("request")
    run_parser.add_argument("--skill", help="跳过自动匹配，指定使用某个 skill")
    run_parser.add_argument("--output-dir", default="outputs/skill_runs")
    run_parser.add_argument("--svg", help="图表 skill 使用：传入已有 SVG 并转换成 PNG")
    run_parser.add_argument("--load-all-refs", action="store_true")
    run_parser.add_argument("--json", action="store_true", help="输出机器可读的 JSON 结果")

    args = parser.parse_args()
    registry = SkillRegistry(Path(args.skills_dir))

    if args.command == "list":
        list_skills(registry)
    elif args.command == "match":
        print_matches(args.request, registry, top_k=args.top_k)
    elif args.command == "inspect":
        inspect_skill(args, registry)
    elif args.command == "run":
        run_skill(args, registry)


def list_skills(registry: SkillRegistry) -> None:
    skills = registry.discover()
    print(f"[stage 0] 只读取元数据，发现 {len(skills)} 个 skills")
    for skill in skills:
        version = f" v{skill.version}" if skill.version else ""
        print(f"- {skill.name}{version} ({skill.frontmatter_chars} 个 frontmatter 字符)")
        if skill.description:
            print(f"  {shorten(skill.description, 120)}")


def print_matches(request: str, registry: SkillRegistry, *, top_k: int) -> list[MatchResult]:
    skills = registry.discover()
    print(f"[stage 0] 只读取元数据，发现 {len(skills)} 个 skills")
    matches = SkillMatcher().rank(request, skills)[:top_k]
    for idx, match in enumerate(matches, start=1):
        reasons = f" reasons={', '.join(match.reasons)}" if match.reasons else ""
        print(f"{idx}. {match.skill.name} score={match.score}{reasons}")
    return matches


def inspect_skill(args: argparse.Namespace, registry: SkillRegistry) -> None:
    metadata = registry.get(args.skill)
    print("[stage 0] 已根据元数据选中 skill")
    context = ProgressiveLoader().build_context(
        args.request,
        metadata,
        load_all_refs=args.load_all_refs,
    )
    for item in context.trace:
        print(item)
    print(f"上下文总量估算：约 {context.total_token_estimate} tokens")


def run_skill(args: argparse.Namespace, registry: SkillRegistry) -> None:
    skills = registry.discover()
    trace = [f"stage 0: 只读取元数据，发现 {len(skills)} 个 skills"]
    if args.skill:
        metadata = registry.get(args.skill)
        trace.append(f"stage 0: 通过 --skill 指定 {metadata.name}")
    else:
        matches = SkillMatcher().rank(args.request, skills)
        if not matches:
            raise SystemExit("没有匹配到合适的 skill。")
        metadata = matches[0].skill
        trace.append(
            f"stage 0: matcher 选中 {metadata.name} "
            f"(score={matches[0].score}, reasons={', '.join(matches[0].reasons)})"
        )

    loader = ProgressiveLoader()
    context = loader.build_context(args.request, metadata, load_all_refs=args.load_all_refs)
    context.trace = trace + context.trace
    context.options.update({"output_dir": args.output_dir, "svg": args.svg})
    result = RunnerRegistry().run(context)

    if args.json:
        payload = {
            "status": result.status,
            "message": result.message,
            "artifacts": {k: str(v) for k, v in result.artifacts.items()},
            "returncode": result.returncode,
            "trace": context.trace,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    for item in context.trace:
        print(item)
    print(f"结果: {result.status} - {result.message}")
    for name, path in result.artifacts.items():
        print(f"产物[{name}]: {path}")
    if result.stdout.strip():
        print("stdout:")
        print(result.stdout.strip())
    if result.stderr.strip():
        print("stderr:")
        print(result.stderr.strip())


def shorten(text: str, width: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= width:
        return compact
    return compact[: width - 3] + "..."


if __name__ == "__main__":
    main()
