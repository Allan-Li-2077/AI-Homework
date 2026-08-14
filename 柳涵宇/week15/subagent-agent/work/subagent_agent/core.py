from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Iterable


Worker = Callable[["Task"], Awaitable[str]]


@dataclass(frozen=True)
class Task:
    """A unit of work that can be routed to a matching subagent."""

    title: str
    description: str
    kind: str = "general"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass(frozen=True)
class TaskResult:
    """The normalized result returned by every subagent run."""

    task_id: str
    task_title: str
    subagent: str
    ok: bool
    output: str
    elapsed_seconds: float
    error: str | None = None


class SubAgent:
    """Executes tasks for one or more task kinds."""

    def __init__(self, name: str, accepts: Iterable[str], worker: Worker) -> None:
        self.name = name
        self.accepts = set(accepts)
        self._worker = worker

    def can_handle(self, task: Task) -> bool:
        return task.kind in self.accepts or "general" in self.accepts

    async def run(self, task: Task) -> TaskResult:
        started = time.perf_counter()
        try:
            output = await self._worker(task)
            return TaskResult(
                task_id=task.id,
                task_title=task.title,
                subagent=self.name,
                ok=True,
                output=output,
                elapsed_seconds=round(time.perf_counter() - started, 3),
            )
        except Exception as exc:  # noqa: BLE001 - isolate worker failures.
            return TaskResult(
                task_id=task.id,
                task_title=task.title,
                subagent=self.name,
                ok=False,
                output="",
                elapsed_seconds=round(time.perf_counter() - started, 3),
                error=f"{type(exc).__name__}: {exc}",
            )


class Agent:
    """Routes tasks to subagents and runs them concurrently."""

    def __init__(self, subagents: Iterable[SubAgent], max_parallel: int = 4) -> None:
        self.subagents = list(subagents)
        self.max_parallel = max_parallel

    async def run(self, tasks: Iterable[Task]) -> list[TaskResult]:
        semaphore = asyncio.Semaphore(self.max_parallel)
        jobs = [self._run_one(task, semaphore) for task in tasks]
        return await asyncio.gather(*jobs)

    async def _run_one(self, task: Task, semaphore: asyncio.Semaphore) -> TaskResult:
        subagent = self._select_subagent(task)
        async with semaphore:
            return await subagent.run(task)

    def _select_subagent(self, task: Task) -> SubAgent:
        for subagent in self.subagents:
            if subagent.can_handle(task):
                return subagent
        raise ValueError(f"No subagent can handle task kind: {task.kind}")


async def research_worker(task: Task) -> str:
    await asyncio.sleep(0.6)
    return (
        f"Research notes for '{task.title}': identified context, assumptions, "
        "risks, and 3 useful follow-up questions."
    )


async def code_worker(task: Task) -> str:
    await asyncio.sleep(0.8)
    return (
        f"Implementation sketch for '{task.title}': define interfaces, add tests, "
        "then wire the feature behind a small CLI command."
    )


async def review_worker(task: Task) -> str:
    await asyncio.sleep(0.4)
    return (
        f"Review for '{task.title}': checked failure handling, observability, "
        "and whether the output can be reproduced."
    )


async def writing_worker(task: Task) -> str:
    await asyncio.sleep(0.5)
    return (
        f"Draft for '{task.title}': concise summary, action list, and final "
        "handoff notes for the user."
    )


async def general_worker(task: Task) -> str:
    await asyncio.sleep(0.3)
    return f"Handled '{task.title}' as a general task: {task.description}"


def default_agent(max_parallel: int = 4) -> Agent:
    return Agent(
        subagents=[
            SubAgent("research-agent", ["research"], research_worker),
            SubAgent("code-agent", ["code"], code_worker),
            SubAgent("review-agent", ["review"], review_worker),
            SubAgent("writing-agent", ["write"], writing_worker),
            SubAgent("general-agent", ["general"], general_worker),
        ],
        max_parallel=max_parallel,
    )


def load_tasks(path: Path) -> list[Task]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Task file must contain a JSON array.")
    return [Task(**item) for item in raw]


def sample_tasks() -> list[Task]:
    return [
        Task(
            title="Compare orchestration options",
            kind="research",
            description="Gather tradeoffs for sequential vs parallel task dispatch.",
        ),
        Task(
            title="Build dispatcher",
            kind="code",
            description="Create a small API that routes work to matching subagents.",
        ),
        Task(
            title="Audit edge cases",
            kind="review",
            description="Check timeout, failure, and missing-route behavior.",
        ),
        Task(
            title="Write handoff",
            kind="write",
            description="Summarize what each subagent produced.",
        ),
    ]


def format_report(results: Iterable[TaskResult]) -> str:
    lines = ["# Subagent Run Report", ""]
    for result in results:
        status = "OK" if result.ok else "FAILED"
        lines.extend(
            [
                f"## {result.task_title}",
                f"- Task ID: `{result.task_id}`",
                f"- Subagent: `{result.subagent}`",
                f"- Status: `{status}`",
                f"- Elapsed: `{result.elapsed_seconds}s`",
            ]
        )
        if result.ok:
            lines.append(f"- Output: {result.output}")
        else:
            lines.append(f"- Error: {result.error}")
        lines.append("")
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    tasks = load_tasks(args.tasks) if args.tasks else sample_tasks()
    agent = default_agent(max_parallel=args.max_parallel)
    started = time.perf_counter()
    results = await agent.run(tasks)
    elapsed = round(time.perf_counter() - started, 3)

    payload = {
        "elapsed_seconds": elapsed,
        "max_parallel": args.max_parallel,
        "results": [asdict(result) for result in results],
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_report(results))
        print(f"Total elapsed: {elapsed}s")
    return 0 if all(result.ok for result in results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run multiple tasks concurrently through specialized subagents."
    )
    parser.add_argument(
        "--tasks",
        type=Path,
        help="Path to a JSON array of tasks. Defaults to built-in sample tasks.",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=4,
        help="Maximum number of subagents running at once.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    return parser


def main() -> int:
    return asyncio.run(main_async(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
