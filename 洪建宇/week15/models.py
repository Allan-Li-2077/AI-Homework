"""核心数据模型定义。

本模块定义贯穿整个调度系统生命周期的数据结构，包括任务上下文、子任务、
执行计划（DAG）、执行结果与执行报告等。所有模块均通过这些数据结构交互，
保证接口清晰、可独立测试。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


def gen_id(prefix: str = "") -> str:
    """生成全局唯一 ID。"""
    return f"{prefix}{uuid.uuid4().hex[:12]}"


class TaskStatus(str, Enum):
    """主任务状态。"""
    PENDING = "pending"
    DECOMPOSING = "decomposing"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    FAILED = "failed"


class SubTaskStatus(str, Enum):
    """子任务状态。"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class Priority(int, Enum):
    """任务优先级。"""
    LOW = 1
    NORMAL = 5
    HIGH = 8
    URGENT = 10

    @classmethod
    def valid(cls, value: int) -> bool:
        return any(value == p.value for p in cls)


class HealthState(str, Enum):
    """SubAgent 健康状态。"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass
class SubTask:
    """子任务定义。"""
    id: str
    parent_task_id: str
    name: str
    description: str
    capability: str  # 能力标签，如 "info_retrieval"
    dependencies: List[str] = field(default_factory=list)  # 前置子任务 ID
    input_data: Any = None
    timeout: float = 60.0
    status: SubTaskStatus = SubTaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    assigned_agent: Optional[str] = None
    retry_count: int = 0
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    @property
    def duration(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "parent_task_id": self.parent_task_id,
            "name": self.name,
            "description": self.description,
            "capability": self.capability,
            "dependencies": list(self.dependencies),
            "timeout": self.timeout,
            "status": self.status.value,
            "assigned_agent": self.assigned_agent,
            "retry_count": self.retry_count,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class ExecutionPlan:
    """执行计划：以 DAG 形式组织子任务。

    edges 为依赖边列表，每条边 (src, dst) 表示 dst 依赖 src。
    parallel_groups 是拓扑排序后的并行分组，同组内任务可并行。
    """
    subtasks: List[SubTask] = field(default_factory=list)
    edges: List[tuple] = field(default_factory=list)

    @property
    def subtask_map(self) -> Dict[str, SubTask]:
        return {st.id: st for st in self.subtasks}

    def successors(self, subtask_id: str) -> List[str]:
        return [dst for (src, dst) in self.edges if src == subtask_id]

    def predecessors(self, subtask_id: str) -> List[str]:
        return [src for (src, dst) in self.edges if dst == subtask_id]

    def compute_parallel_groups(self) -> List[List[str]]:
        """拓扑排序计算并行分组（Kahn 算法）。"""
        indeg: Dict[str, int] = {st.id: 0 for st in self.subtasks}
        adj: Dict[str, List[str]] = {st.id: [] for st in self.subtasks}
        for src, dst in self.edges:
            adj[src].append(dst)
            indeg[dst] += 1
        groups: List[List[str]] = []
        ready = [sid for sid, d in indeg.items() if d == 0]
        processed = 0
        while ready:
            groups.append(sorted(ready))
            next_ready: List[str] = []
            for sid in ready:
                for nxt in adj[sid]:
                    indeg[nxt] -= 1
                    if indeg[nxt] == 0:
                        next_ready.append(nxt)
                processed += 1
            ready = next_ready
        if processed != len(indeg):
            raise ValueError("执行计划中存在环依赖，无法完成拓扑排序")
        return groups

    def is_empty(self) -> bool:
        return len(self.subtasks) == 0


@dataclass
class TaskContext:
    """任务上下文：贯穿整个生命周期的唯一数据载体。"""
    task_id: str
    original_input: Any
    input_format: str  # "text" 或 "json"
    priority: Priority
    timeout: float
    created_at: float
    status: TaskStatus = TaskStatus.PENDING
    plan: Optional[ExecutionPlan] = None
    manual_plan: Optional[ExecutionPlan] = None  # 用户手动覆盖的拆解方案
    results: Dict[str, Any] = field(default_factory=dict)  # subtask_id -> result
    report: Optional[Dict[str, Any]] = None
    final_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    idempotency_key: Optional[str] = None  # 幂等键

    def to_summary(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "priority": self.priority.name,
            "timeout": self.timeout,
            "created_at": self.created_at,
            "subtask_count": len(self.plan.subtasks) if self.plan else 0,
        }
