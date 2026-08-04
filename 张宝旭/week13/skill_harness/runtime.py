from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from week13.skill_harness.registry import LoadedSkill


FUNCTION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)(\?)?\s*\}\}")


@dataclass(frozen=True)
class RuntimeToolRef:
    skill: LoadedSkill
    tool: dict[str, Any]


def runtime_tool_refs(skills: Iterable[LoadedSkill]) -> tuple[RuntimeToolRef, ...]:
    refs: list[RuntimeToolRef] = []
    seen: set[tuple[str, str]] = set()
    for skill in skills:
        runtime = skill.manifest.runtime_v2 or {}
        tools = runtime.get("tools") if isinstance(runtime.get("tools"), list) else []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "").strip()
            key = (skill.id, name.lower())
            if not is_valid_function_name(name) or key in seen:
                continue
            seen.add(key)
            refs.append(RuntimeToolRef(skill=skill, tool=tool))
    return tuple(refs)


def tool_schemas_for_skills(skills: Iterable[LoadedSkill]) -> list[dict[str, Any]]:
    """Expose only tools declared by skills loaded for the current task."""

    schemas: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for ref in runtime_tool_refs(skills):
        name = str(ref.tool.get("name") or "").strip()
        if name in seen_names:
            continue
        schema = ref.tool.get("inputSchema") if isinstance(ref.tool.get("inputSchema"), dict) else {}
        if schema.get("type") != "object":
            schema = {"type": "object", "properties": {}, "additionalProperties": True}
        description = str(ref.tool.get("description") or f"Runtime tool provided by {ref.skill.id}.").strip()
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema,
                },
            }
        )
        seen_names.add(name)
    return schemas


def execute_runtime_tool(
    tool_name: str,
    args: dict[str, Any],
    cwd: Path,
    skills: Iterable[LoadedSkill],
    env_overrides: dict[str, str] | None = None,
) -> str:
    """Execute a runtime tool declared by one of the already-loaded skills."""

    ref = find_tool_ref(tool_name, skills)
    if ref is None:
        raise ValueError(f"Runtime tool is not loaded for this task: {tool_name}")

    runner = ref.tool.get("runner") if isinstance(ref.tool.get("runner"), dict) else {}
    runner_type = str(runner.get("type") or "").strip().lower()
    timeout_seconds = read_int(runner.get("timeoutSeconds") or runner.get("timeout_seconds"), 20)

    if runner_type == "python":
        script = resolve_skill_file(ref.skill.directory, str(runner.get("script") or ""))
        argv = [sys.executable, str(script), *render_arg_template(runner.get("args"), args)]
        return run_argv(argv, cwd=cwd, env_overrides=env_overrides or {}, timeout_seconds=timeout_seconds)

    if runner_type == "command":
        executable = str(runner.get("executable") or runner.get("command") or "").strip()
        if not executable:
            raise ValueError("Command runner requires executable.")
        argv = [executable, *render_arg_template(runner.get("args"), args)]
        return run_argv(argv, cwd=cwd, env_overrides=env_overrides or {}, timeout_seconds=timeout_seconds)

    if runner_type == "inline-json":
        return json.dumps({"tool": tool_name, "args": args, "skill": ref.skill.id}, ensure_ascii=False)

    raise ValueError(f"Unsupported runtime runner type: {runner_type or 'missing'}")


def find_tool_ref(tool_name: str, skills: Iterable[LoadedSkill]) -> RuntimeToolRef | None:
    clean_name = str(tool_name or "").strip()
    for ref in runtime_tool_refs(skills):
        if str(ref.tool.get("name") or "").strip() == clean_name:
            return ref
    return None


def render_arg_template(template: Any, args: dict[str, Any]) -> list[str]:
    if not isinstance(template, list):
        return []

    rendered: list[str] = []
    skip_next_flag = False
    for index, item in enumerate(template):
        text = str(item)
        placeholder_match = PLACEHOLDER_PATTERN.fullmatch(text.strip())
        if placeholder_match:
            name, optional = placeholder_match.group(1), bool(placeholder_match.group(2))
            value = args.get(name)
            if value is None or value == "":
                if optional:
                    skip_next_flag = bool(rendered and rendered[-1].startswith("-"))
                    if skip_next_flag:
                        rendered.pop()
                    continue
                raise ValueError(f"Missing required runtime argument: {name}")
            rendered.extend(coerce_arg_values(value))
            continue

        def replace(match: re.Match[str]) -> str:
            name, optional = match.group(1), bool(match.group(2))
            value = args.get(name)
            if value is None or value == "":
                if optional:
                    return ""
                raise ValueError(f"Missing required runtime argument: {name}")
            return str(value)

        output = PLACEHOLDER_PATTERN.sub(replace, text)
        if output or index == 0:
            rendered.append(output)
    return rendered


def run_argv(
    argv: list[str],
    cwd: Path,
    env_overrides: dict[str, str],
    timeout_seconds: int,
) -> str:
    completed = subprocess.run(
        argv,
        cwd=str(cwd),
        env={**dict(os_environ()), **env_overrides},
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if completed.returncode != 0:
        raise RuntimeError(f"Runtime tool failed with exit code {completed.returncode}: {error or output}")
    return output or error


def resolve_skill_file(skill_dir: Path, relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("Python runner requires script.")
    root = skill_dir.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Runner script escapes skill directory: {relative_path}") from error
    if not target.is_file():
        raise FileNotFoundError(f"Runner script does not exist: {target}")
    return target


def os_environ() -> dict[str, str]:
    import os

    return dict(os.environ)


def coerce_arg_values(value: Any) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return [str(value)]


def is_valid_function_name(name: str) -> bool:
    return bool(FUNCTION_NAME_PATTERN.fullmatch(name))


def read_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
