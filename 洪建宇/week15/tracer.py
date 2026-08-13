"""执行轨迹记录器。

按任务 ID 维护完整的事件时间线，支持按任务 ID 查询从创建到结束的全部事件。
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Dict, List


class Tracer:
    """按 task_id 存储事件时间线，线程安全。"""

    def __init__(self) -> None:
        self._traces: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._lock = threading.Lock()

    def record(self, event: Dict[str, Any]) -> None:
        task_id = event.get("task_id", "_global")
        with self._lock:
            self._traces[task_id].append(event)

    def get(self, task_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._traces.get(task_id, []))

    def all_tasks(self) -> List[str]:
        with self._lock:
            return list(self._traces.keys())

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()
