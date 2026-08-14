"""核心指标采集器。

统计并暴露系统运行指标，包括活跃任务数、并行子任务数、各 SubAgent 负载与成功率、
任务端到端耗时、子任务执行耗时、失败率与重试率。预留 Prometheus 对接接口。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, Optional


class Metrics:
    """线程安全的指标采集器。"""

    # 滑动窗口大小，用于计算近平均值
    _WINDOW = 200

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # 计数类指标
        self.active_tasks: int = 0
        self.running_subtasks: int = 0
        self.total_tasks: int = 0
        self.completed_tasks: int = 0
        self.failed_tasks: int = 0
        # 子任务统计
        self.total_subtasks: int = 0
        self.completed_subtasks: int = 0
        self.failed_subtasks: int = 0
        self.retried_subtasks: int = 0
        # SubAgent 维度
        self.agent_total: Dict[str, int] = defaultdict(int)
        self.agent_success: Dict[str, int] = defaultdict(int)
        self.agent_failed: Dict[str, int] = defaultdict(int)
        self.agent_current: Dict[str, int] = defaultdict(int)
        # 耗时滑动窗口
        self._subtask_durations: deque = deque(maxlen=self._WINDOW)
        self._task_durations: deque = deque(maxlen=self._WINDOW)

    # ---- 任务级 ----
    def task_started(self) -> None:
        with self._lock:
            self.active_tasks += 1
            self.total_tasks += 1

    def task_finished(self, success: bool, duration: float) -> None:
        with self._lock:
            self.active_tasks = max(0, self.active_tasks - 1)
            if success:
                self.completed_tasks += 1
            else:
                self.failed_tasks += 1
            self._task_durations.append(duration)

    # ---- 子任务级 ----
    def subtask_created(self) -> None:
        with self._lock:
            self.total_subtasks += 1

    def subtask_started(self, agent_name: str) -> None:
        with self._lock:
            self.running_subtasks += 1
            self.agent_current[agent_name] += 1

    def subtask_finished(
        self, agent_name: str, success: bool, duration: float, retried: bool = False
    ) -> None:
        with self._lock:
            self.running_subtasks = max(0, self.running_subtasks - 1)
            self.agent_current[agent_name] = max(0, self.agent_current[agent_name] - 1)
            self.agent_total[agent_name] += 1
            if success:
                self.completed_subtasks += 1
                self.agent_success[agent_name] += 1
            else:
                self.failed_subtasks += 1
                self.agent_failed[agent_name] += 1
            if retried:
                self.retried_subtasks += 1
            self._subtask_durations.append(duration)

    def subtask_retried(self) -> None:
        with self._lock:
            self.retried_subtasks += 1

    # ---- 查询 ----
    @staticmethod
    def _avg(seq: deque) -> float:
        return sum(seq) / len(seq) if seq else 0.0

    def agent_stats(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            stats = {}
            for name, total in self.agent_total.items():
                succ = self.agent_success.get(name, 0)
                stats[name] = {
                    "current_load": self.agent_current.get(name, 0),
                    "total_runs": total,
                    "success": succ,
                    "failed": self.agent_failed.get(name, 0),
                    "success_rate": round(succ / total, 4) if total else 0.0,
                }
            return stats

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            total_sub = self.total_subtasks
            total_tasks = self.total_tasks
            return {
                "active_tasks": self.active_tasks,
                "running_subtasks": self.running_subtasks,
                "total_tasks": total_tasks,
                "completed_tasks": self.completed_tasks,
                "failed_tasks": self.failed_tasks,
                "total_subtasks": total_sub,
                "completed_subtasks": self.completed_subtasks,
                "failed_subtasks": self.failed_subtasks,
                "retried_subtasks": self.retried_subtasks,
                "failure_rate": round(self.failed_subtasks / total_sub, 4) if total_sub else 0.0,
                "retry_rate": round(self.retried_subtasks / total_sub, 4) if total_sub else 0.0,
                "avg_subtask_duration": round(self._avg(self._subtask_durations), 4),
                "avg_task_duration": round(self._avg(self._task_durations), 4),
                "agents": self.agent_stats(),
                "ts": time.time(),
            }

    def render_prometheus(self) -> str:
        """以 Prometheus 文本格式暴露指标，便于外部监控系统抓取。"""
        snap = self.snapshot()
        lines = [
            f"pa_active_tasks {snap['active_tasks']}",
            f"pa_running_subtasks {snap['running_subtasks']}",
            f"pa_total_tasks {snap['total_tasks']}",
            f"pa_completed_tasks {snap['completed_tasks']}",
            f"pa_failed_tasks {snap['failed_tasks']}",
            f"pa_total_subtasks {snap['total_subtasks']}",
            f"pa_failed_subtasks {snap['failed_subtasks']}",
            f"pa_retried_subtasks {snap['retried_subtasks']}",
            f"pa_avg_subtask_duration {snap['avg_subtask_duration']}",
            f"pa_avg_task_duration {snap['avg_task_duration']}",
        ]
        for name, st in snap["agents"].items():
            label = name.replace('"', "")
            lines.append(f'pa_agent_total_runs{{agent="{label}"}} {st["total_runs"]}')
            lines.append(f'pa_agent_current_load{{agent="{label}"}} {st["current_load"]}')
            lines.append(f'pa_agent_success_rate{{agent="{label}"}} {st["success_rate"]}')
        return "\n".join(lines) + "\n"
