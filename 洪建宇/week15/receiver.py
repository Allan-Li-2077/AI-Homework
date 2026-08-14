"""任务接收与解析模块。

提供统一的任务提交入口，接受自然语言文本与 JSON 结构体两种格式。
完成参数校验、全局唯一 ID 生成、任务上下文初始化与幂等性处理。
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Union

from ..core.context import TaskStore
from ..core.exceptions import ValidationError
from ..core.models import Priority, TaskContext, TaskStatus, gen_id
from ..monitor import get_monitor

DEFAULT_TIMEOUT = 120.0


class TaskReceiver:
    """任务接收与解析。"""

    def __init__(self, store: TaskStore = None, monitor=None) -> None:
        self.store = store or TaskStore()
        self._monitor = monitor or get_monitor()

    def receive(self, raw_input: Union[str, Dict[str, Any]]) -> TaskContext:
        """接收原始任务输入，返回任务上下文。

        若为重复提交（幂等键命中），返回已有任务的上下文而非新建。
        校验失败时抛出 ValidationError。
        """
        key = self._idempotency_key(raw_input)
        existing = self.store.get_by_key(key)
        if existing is not None:
            self._monitor.emit(
                existing.task_id, "idempotent_hit", "receiver",
                {"existing_task_id": existing.task_id, "status": existing.status.value},
            )
            return existing

        # 解析输入
        if isinstance(raw_input, str):
            fmt = "text"
            text = raw_input.strip()
            if not text:
                raise ValidationError("EMPTY_INPUT", "自然语言任务描述不能为空")
            description = text
            priority = Priority.NORMAL
            timeout = DEFAULT_TIMEOUT
            name = text[:32]
        elif isinstance(raw_input, dict):
            fmt = "json"
            self._validate_json(raw_input)
            description = raw_input.get("description") or raw_input.get("task") or ""
            name = raw_input.get("name") or description[:32] or "unnamed"
            prio_val = raw_input.get("priority", Priority.NORMAL.value)
            priority = Priority(int(prio_val))
            timeout = float(raw_input.get("timeout", DEFAULT_TIMEOUT))
        else:
            raise ValidationError("INVALID_FORMAT", "输入必须为字符串或 JSON 对象")

        # 构造任务上下文
        task_id = gen_id("task_")
        now = time.time()
        ctx = TaskContext(
            task_id=task_id,
            original_input=raw_input,
            input_format=fmt,
            priority=priority,
            timeout=timeout,
            created_at=now,
            status=TaskStatus.PENDING,
            idempotency_key=key,
        )
        self.store.save(ctx)
        self._monitor.emit(
            task_id, "task_received", "receiver",
            {"format": fmt, "name": name, "priority": priority.name,
             "timeout": timeout, "description_preview": description[:80]},
        )
        return ctx

    def _validate_json(self, payload: Dict[str, Any]) -> None:
        """JSON 输入参数校验。"""
        if not isinstance(payload, dict):
            raise ValidationError("INVALID_FORMAT", "JSON 输入必须为对象")

        desc = payload.get("description") or payload.get("task") or payload.get("name")
        if not desc:
            raise ValidationError(
                "MISSING_FIELD", "缺少必填字段：description / task / name 至少需一个")

        timeout = payload.get("timeout")
        if timeout is not None:
            try:
                t = float(timeout)
            except (TypeError, ValueError):
                raise ValidationError("INVALID_TIMEOUT", "超时时间必须为数字")
            if t <= 0:
                raise ValidationError("INVALID_TIMEOUT", "超时时间必须为正数")

        priority = payload.get("priority")
        if priority is not None:
            try:
                p = int(priority)
            except (TypeError, ValueError):
                raise ValidationError("INVALID_PRIORITY", "优先级必须为整数")
            if not Priority.valid(p):
                raise ValidationError(
                    "INVALID_PRIORITY",
                    f"优先级 {p} 不在允许范围 {[p.value for p in Priority]}",
                )

    def _idempotency_key(self, raw_input: Any) -> str:
        """根据原始输入生成幂等键。"""
        if isinstance(raw_input, dict):
            src = json.dumps(raw_input, sort_keys=True, ensure_ascii=False, default=str)
        else:
            src = str(raw_input)
        return hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]
