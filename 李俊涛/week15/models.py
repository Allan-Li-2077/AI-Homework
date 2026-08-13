"""
多智能体协作框架 — 数据模型

定义任务、子智能体规格、单任务执行结果与汇总结果的结构。
所有跨模块流转的数据都以这些 dataclass 为载体，保证类型清晰、可序列化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import time


class TaskStatus(str, Enum):
    """任务在执行生命周期中的状态。"""
    PENDING = "pending"      # 待调度
    RUNNING = "running"      # 执行中
    SUCCESS = "success"      # 成功
    FAILED = "failed"        # 失败（异常且重试耗尽）
    TIMEOUT = "timeout"      # 超时
    RETRYING = "retrying"    # 重试中


@dataclass
class Task:
    """一个待执行的子任务（最小调度单元）。"""

    task_id: str
    name: str
    payload: Any = None                 # 交给 backend 执行的负载（函数 / 提示词 / 命令）
    route_key: str | None = None        # 分发路由键（by_key 策略使用）
    dependencies: list[str] = field(default_factory=list)  # 依赖的 task_id
    timeout: float | None = None        # 单任务超时（秒），None 用 Orchestrator 默认值
    max_retries: int = 0                # 失败后最大重试次数
    retry_backoff: float = 0.5          # 重试退避间隔（秒）
    metadata: dict = field(default_factory=dict)

    def depends_on(self, *task_ids: str) -> "Task":
        """链式声明依赖，返回 self 便于流式构造。"""
        self.dependencies.extend(task_ids)
        return self


@dataclass
class TaskResult:
    """单个任务的最终执行结果（含异常信息，永不抛出到调度层）。"""

    task_id: str
    name: str
    status: TaskStatus
    value: Any = None
    error: str | None = None
    error_type: str | None = None
    attempts: int = 0
    subagent_name: str | None = None
    route_key: str | None = None
    usage: dict | None = None          # token 用量
    started_at: float = 0.0             # 相对进程启动的 perf_counter 时间戳
    finished_at: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.finished_at - self.started_at)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status.value,
            "value": self.value,
            "error": self.error,
            "error_type": self.error_type,
            "attempts": self.attempts,
            "subagent_name": self.subagent_name,
            "route_key": self.route_key,
            "started_at": round(self.started_at, 4),
            "finished_at": round(self.finished_at, 4),
            "duration": round(self.duration, 4),
        }


@dataclass
class AggregatedResults:
    """主 Agent 统一收集后的全量结果汇总。"""

    results: list[TaskResult] = field(default_factory=list)
    wall_start: float = 0.0             # 整轮调度的起始时间戳
    wall_end: float = 0.0              # 整轮调度的结束时间戳

    # ── 统计 ──────────────────────────────────────────
    def summary(self) -> dict:
        total = len(self.results)
        succ = [r for r in self.results if r.status == TaskStatus.SUCCESS]
        fail = [r for r in self.results if r.status == TaskStatus.FAILED]
        to = [r for r in self.results if r.status == TaskStatus.TIMEOUT]
        sum_dur = sum(r.duration for r in self.results)
        wall = max(0.0, self.wall_end - self.wall_start)
        usage = self.total_usage()
        return {
            "total": total,
            "succeeded": len(succ),
            "failed": len(fail),
            "timed_out": len(to),
            "total_compute_seconds": round(sum_dur, 3),   # 各任务耗时之和（串行视角）
            "wall_seconds": round(wall, 3),               # 实际墙钟耗时（并发视角）
            "speedup": round(sum_dur / wall, 2) if wall > 0 else 0.0,
            "tokens_total": usage["total_tokens"],
            "tokens_prompt": usage["prompt_tokens"],
            "tokens_completion": usage["completion_tokens"],
            "tokens_estimated": usage["estimated"],
        }

    def total_usage(self) -> dict:
        """归集所有任务的 token 用量（仅 LLM 后端会产生）。"""
        tot = {"prompt_tokens": 0, "completion_tokens": 0,
               "total_tokens": 0, "estimated": False}
        for r in self.results:
            if r.usage:
                tot["prompt_tokens"] += r.usage.get("prompt_tokens", 0)
                tot["completion_tokens"] += r.usage.get("completion_tokens", 0)
                tot["total_tokens"] += r.usage.get("total_tokens", 0)
                if r.usage.get("estimated"):
                    tot["estimated"] = True
        return tot

    def by_subagent(self) -> dict[str, list[TaskResult]]:
        out: dict[str, list[TaskResult]] = {}
        for r in self.results:
            out.setdefault(r.subagent_name or "unknown", []).append(r)
        return out

    def get_success_values(self) -> dict[str, Any]:
        return {
            r.task_id: r.value
            for r in self.results
            if r.status == TaskStatus.SUCCESS
        }

    def get_failures(self) -> list[TaskResult]:
        return [r for r in self.results if r.status != TaskStatus.SUCCESS]

    def to_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "by_subagent": {
                name: [r.to_dict() for r in rs]
                for name, rs in self.by_subagent().items()
            },
            "tasks": [r.to_dict() for r in self.results],
            "wall_start": round(self.wall_start, 4),
            "wall_end": round(self.wall_end, 4),
        }
