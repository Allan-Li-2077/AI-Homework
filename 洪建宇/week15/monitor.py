"""监控主模块：结构化日志 + 执行轨迹 + 指标采集的统一入口。

在任务接收、拆解完成、子任务下发、状态变更、聚合、回传等关键节点，
系统均通过 Monitor.emit 输出结构化日志（含时间戳、任务 ID、事件类型、
模块名称与关键数据摘要），同时写入执行轨迹并更新指标。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, Optional

from .metrics import Metrics
from .tracer import Tracer

_logger = logging.getLogger("parallel_agent")


class Monitor:
    """统一监控入口，聚合 Tracer 与 Metrics。"""

    def __init__(self, tracer: Optional[Tracer] = None, metrics: Optional[Metrics] = None) -> None:
        self.tracer = tracer or Tracer()
        self.metrics = metrics or Metrics()
        self._lock = threading.Lock()

    def emit(
        self,
        task_id: str,
        event_type: str,
        module: str,
        data: Optional[Dict[str, Any]] = None,
        level: str = "INFO",
    ) -> Dict[str, Any]:
        """输出一条结构化事件日志并记录轨迹。

        Args:
            task_id: 所属任务 ID（全局事件可用 "_global"）。
            event_type: 事件类型，如 "task_received" / "subtask_dispatched"。
            module: 产生事件的模块名称。
            data: 关键数据摘要。
            level: 日志级别。
        """
        event = {
            "ts": time.time(),
            "task_id": task_id,
            "event_type": event_type,
            "module": module,
            "level": level,
            "data": data or {},
        }
        self.tracer.record(event)
        # 结构化日志：单行 JSON，便于采集与检索
        log_msg = json.dumps(event, ensure_ascii=False, default=str)
        if level == "ERROR":
            _logger.error(log_msg)
        elif level == "WARNING":
            _logger.warning(log_msg)
        else:
            _logger.info(log_msg)
        return event

    # ---- 轨迹查询 ----
    def get_trace(self, task_id: str) -> list:
        return self.tracer.get(task_id)

    # ---- 指标查询 ----
    def metrics_snapshot(self) -> Dict[str, Any]:
        return self.metrics.snapshot()

    def render_prometheus(self) -> str:
        return self.metrics.render_prometheus()


# 全局单例（支持测试时替换）
_global_monitor: Optional[Monitor] = None
_global_lock = threading.Lock()


def get_monitor() -> Monitor:
    global _global_monitor
    with _global_lock:
        if _global_monitor is None:
            _global_monitor = Monitor()
        return _global_monitor


def set_monitor(mon: Monitor) -> None:
    """替换全局 Monitor（主要用于测试注入）。"""
    global _global_monitor
    with _global_lock:
        _global_monitor = mon
