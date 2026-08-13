"""SubAgent 基类定义。

每个 SubAgent 作为独立的无状态工作节点，接收子任务后调用自身处理逻辑执行。
基类统一处理同步/异步处理函数的兼容、异常捕获、状态封装与并发计数，
子类只需实现 `process` 方法（同步或异步均可）。
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from ..core.models import HealthState, SubTask


class BaseSubAgent:
    """SubAgent 抽象基类。

    子类应实现 ``process(subtask)`` 方法，返回任意可序列化的结果。
    处理函数可以是同步函数或异步函数，基类会自动兼容。
    """

    def __init__(
        self,
        name: str,
        capabilities: Union[str, List[str]],
        max_concurrency: int = 5,
    ) -> None:
        self.name = name
        self.capabilities = [capabilities] if isinstance(capabilities, str) else list(capabilities)
        self.max_concurrency = max_concurrency
        self._current = 0  # 当前并发处理数
        self._health = HealthState.HEALTHY
        self._fail_streak = 0  # 连续健康检查失败次数

    # ---- 子类实现 ----
    def process(self, subtask: SubTask) -> Any:
        """实际处理逻辑，子类实现。可为同步或异步。"""
        raise NotImplementedError

    async def health_check(self) -> bool:
        """健康检查，默认返回 True。子类可覆写（如网络探活）。"""
        return True

    # ---- 基类封装 ----
    def _resolve_handler(self, subtask: SubTask) -> Callable:
        """返回实际处理函数。FunctionSubAgent 覆写此方法。"""
        return self.process

    async def handle(self, subtask: SubTask) -> Dict[str, Any]:
        """执行子任务并返回标准化结果。

        返回 dict: {"status": "completed"|"failed", "result": ..., "error": ...}
        取消（CancelledError）会向上抛出，由调度器标记超时/取消状态。
        """
        self._current += 1
        try:
            handler = self._resolve_handler(subtask)
            if inspect.iscoroutinefunction(handler):
                ret = await handler(subtask)
            else:
                # 同步函数放到线程池，避免阻塞事件循环；支持超时取消
                ret = await asyncio.to_thread(handler, subtask)
            self._fail_streak = 0
            return {"status": "completed", "result": ret, "error": None}
        except asyncio.CancelledError:
            # 取消由调度器超时触发，向上传播
            raise
        except Exception as e:  # noqa: BLE001 - 捕获所有处理异常以保证 stateless
            self._fail_streak += 1
            return {"status": "failed", "result": None, "error": f"{type(e).__name__}: {e}"}
        finally:
            self._current = max(0, self._current - 1)

    # ---- 状态查询 ----
    @property
    def current_load(self) -> int:
        return self._current

    @property
    def available_capacity(self) -> int:
        return max(0, self.max_concurrency - self._current)

    @property
    def health_state(self) -> HealthState:
        return self._health

    def set_health(self, state: HealthState) -> None:
        self._health = state

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "capabilities": list(self.capabilities),
            "max_concurrency": self.max_concurrency,
            "current_load": self._current,
            "health": self._health.value,
        }


class FunctionSubAgent(BaseSubAgent):
    """基于处理函数的 SubAgent，便于将普通函数注册为 Agent。"""

    def __init__(
        self,
        name: str,
        capabilities: Union[str, List[str]],
        handler: Callable[[SubTask], Any],
        max_concurrency: int = 5,
    ) -> None:
        super().__init__(name, capabilities, max_concurrency)
        self._handler = handler

    def _resolve_handler(self, subtask: SubTask) -> Callable:
        return self._handler

    def process(self, subtask: SubTask) -> Any:  # 不会被调用，仅占位
        return self._handler(subtask)
