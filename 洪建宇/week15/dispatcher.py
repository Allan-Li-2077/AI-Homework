"""并行调度与下发模块（系统核心）。

按 DAG 执行计划调度子任务：筛选入度为零的子任务并发下发，监听完成事件后
触发后继任务，支持全局并发上限与单 Agent 并发上限、超时熔断、失败重试
（固定间隔/指数退避）。提供纯并行、流水线、自动（DAG）三种下发模式。
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from ..agents.base import BaseSubAgent
from ..agents.registry import AgentRegistry
from ..core.exceptions import NoAgentAvailableError
from ..core.models import (
    ExecutionPlan,
    SubTask,
    SubTaskStatus,
    TaskContext,
    TaskStatus,
)
from ..monitor import get_monitor


class RetryPolicy:
    """失败重试策略。"""

    def __init__(
        self,
        max_retries: int = 2,
        interval: float = 0.3,
        backoff: str = "fixed",  # "fixed" | "exponential"
        base: float = 2.0,
    ) -> None:
        self.max_retries = max_retries
        self.interval = interval
        self.backoff = backoff
        self.base = base

    def delay(self, attempt: int) -> float:
        if self.backoff == "exponential":
            return self.interval * (self.base ** attempt)
        return self.interval


class ParallelDispatcher:
    """并行调度器。"""

    def __init__(
        self,
        registry: AgentRegistry,
        max_global_concurrency: int = 20,
        retry_policy: Optional[RetryPolicy] = None,
        monitor=None,
    ) -> None:
        self.registry = registry
        self.max_global_concurrency = max_global_concurrency
        self.retry_policy = retry_policy or RetryPolicy()
        self._monitor = monitor or get_monitor()
        self._global_sem: Optional[asyncio.Semaphore] = None
        self._agent_sems: Dict[str, asyncio.Semaphore] = {}

    async def execute(self, ctx: TaskContext, mode: str = "auto") -> None:
        """按执行计划调度执行所有子任务，结果写入 ctx.results。

        Args:
            mode: "auto"(按DAG依赖) | "parallel"(忽略依赖全并行) | "pipeline"(严格顺序,上游注入下游)
        """
        plan = ctx.plan
        if plan is None or plan.is_empty():
            ctx.error = "执行计划为空"
            ctx.status = TaskStatus.FAILED
            return

        ctx.status = TaskStatus.RUNNING
        self._global_sem = asyncio.Semaphore(self.max_global_concurrency)
        self._agent_sems = {
            a.name: asyncio.Semaphore(a.max_concurrency) for a in self.registry.all()
        }
        self._monitor.emit(ctx.task_id, "dispatch_start", "dispatcher", {
            "mode": mode, "subtask_count": len(plan.subtasks),
            "max_global_concurrency": self.max_global_concurrency,
        })
        self._monitor.metrics.task_started()

        t0 = time.time()
        try:
            if mode == "parallel":
                await self._run_parallel(ctx, plan)
            elif mode == "pipeline":
                await self._run_pipeline(ctx, plan)
            else:
                await self._run_dag(ctx, plan)
        finally:
            duration = time.time() - t0
            any_success = any(
                ctx.results.get(st.id, {}).get("status") == "completed"
                for st in plan.subtasks
            )
            self._monitor.metrics.task_finished(any_success, duration)
            self._monitor.emit(ctx.task_id, "dispatch_done", "dispatcher", {
                "duration": round(duration, 4),
                "results": {st.id: ctx.results.get(st.id, {}).get("status")
                            for st in plan.subtasks},
            })
            ctx.status = TaskStatus.AGGREGATING

    # ---- 模式一：纯并行（忽略依赖，一次性全部下发） ----
    async def _run_parallel(self, ctx: TaskContext, plan: ExecutionPlan) -> None:
        tasks = [asyncio.create_task(self._run_subtask(ctx, st)) for st in plan.subtasks]
        await asyncio.gather(*tasks, return_exceptions=True)

    # ---- 模式二：流水线（按拓扑组串行，上游结果注入下游） ----
    async def _run_pipeline(self, ctx: TaskContext, plan: ExecutionPlan) -> None:
        groups = plan.compute_parallel_groups()
        prev_group_ids: List[str] = []
        for group in groups:
            coros = [self._run_subtask(ctx, plan.subtask_map[sid]) for sid in group]
            await asyncio.gather(*coros, return_exceptions=True)
            # 将上一组完成结果注入本组各子任务 input_data
            if prev_group_ids:
                upstream = {sid: ctx.results.get(sid, {}).get("result")
                            for sid in prev_group_ids}
                for sid in group:
                    st = plan.subtask_map[sid]
                    if isinstance(st.input_data, dict):
                        st.input_data["upstream_results"] = upstream
            prev_group_ids = list(group)

    # ---- 模式三：DAG 自动调度 ----
    async def _run_dag(self, ctx: TaskContext, plan: ExecutionPlan) -> None:
        indeg: Dict[str, int] = {
            st.id: len(plan.predecessors(st.id)) for st in plan.subtasks
        }
        successors: Dict[str, List[str]] = {
            st.id: plan.successors(st.id) for st in plan.subtasks
        }
        ready: deque = deque([sid for sid, d in indeg.items() if d == 0])
        running: Dict[asyncio.Task, str] = {}

        while ready or running:
            # 下发所有就绪子任务
            while ready:
                sid = ready.popleft()
                st = plan.subtask_map[sid]
                t = asyncio.create_task(self._run_subtask(ctx, st))
                running[t] = sid
            if not running:
                break
            done, _ = await asyncio.wait(running.keys(), return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                sid = running.pop(t)
                exc = t.exception()
                if exc:
                    self._monitor.emit(ctx.task_id, "subtask_crashed", "dispatcher",
                                       {"subtask_id": sid, "error": repr(exc)}, level="ERROR")
                # 触发后继
                for nxt in successors[sid]:
                    indeg[nxt] -= 1
                    if indeg[nxt] == 0:
                        ready.append(nxt)

    # ---- 单个子任务执行 ----
    async def _run_subtask(self, ctx: TaskContext, st: SubTask) -> None:
        """执行单个子任务：选 Agent、限流、超时、重试。"""
        self._monitor.emit(ctx.task_id, "subtask_dispatched", "dispatcher", {
            "subtask_id": st.id, "name": st.name, "capability": st.capability,
        })
        self._monitor.metrics.subtask_created()

        try:
            async with self._global_sem:
                agent = await self._pick_agent(ctx, st)
                st.assigned_agent = agent.name
                st.status = SubTaskStatus.RUNNING
                st.started_at = time.time()
                self._monitor.emit(ctx.task_id, "subtask_started", "dispatcher", {
                    "subtask_id": st.id, "agent": agent.name,
                })
                self._monitor.metrics.subtask_started(agent.name)
                result = await self._execute_with_retry(ctx, st, agent)
                st.finished_at = time.time()
                ctx.results[st.id] = result
                if result.get("status") == "completed":
                    st.status = SubTaskStatus.COMPLETED
                    st.result = result.get("result")
                else:
                    st.status = SubTaskStatus.FAILED
                    st.error = result.get("error")
                self._monitor.metrics.subtask_finished(
                    agent.name,
                    success=(st.status == SubTaskStatus.COMPLETED),
                    duration=(st.finished_at - st.started_at),
                    retried=st.retry_count > 0,
                )
                self._monitor.emit(ctx.task_id, "subtask_finished", "dispatcher", {
                    "subtask_id": st.id, "status": st.status.value,
                    "duration": st.duration, "retry_count": st.retry_count,
                    "agent": agent.name,
                })
        except NoAgentAvailableError as e:
            st.status = SubTaskStatus.FAILED
            st.error = str(e)
            st.finished_at = time.time()
            ctx.results[st.id] = {"status": "failed", "result": None, "error": str(e)}
            self._monitor.emit(ctx.task_id, "subtask_no_agent", "dispatcher",
                               {"subtask_id": st.id, "capability": st.capability,
                                "error": str(e)}, level="WARNING")
        except Exception as e:  # noqa: BLE001
            st.status = SubTaskStatus.FAILED
            st.error = repr(e)
            st.finished_at = time.time()
            ctx.results[st.id] = {"status": "failed", "result": None, "error": repr(e)}
            self._monitor.emit(ctx.task_id, "subtask_error", "dispatcher",
                               {"subtask_id": st.id, "error": repr(e)}, level="ERROR")

    async def _pick_agent(self, ctx: TaskContext, st: SubTask) -> BaseSubAgent:
        """选择有可用容量的 Agent，若无容量则等待。"""
        if not self.registry.query(st.capability):
            raise NoAgentAvailableError(st.capability)
        wait_deadline = time.time() + max(st.timeout, 30.0)
        while True:
            agent = self.registry.select(st.capability)
            if agent is not None:
                return agent
            if time.time() > wait_deadline:
                raise NoAgentAvailableError(st.capability)
            await asyncio.sleep(0.05)

    async def _execute_with_retry(
        self, ctx: TaskContext, st: SubTask, agent: BaseSubAgent
    ) -> Dict[str, Any]:
        """带超时与重试的执行。"""
        last_error: Optional[str] = None
        cur_agent = agent
        tried_agents: List[str] = [agent.name]

        for attempt in range(self.retry_policy.max_retries + 1):
            # 重试时优先尝试同能力其他 Agent
            if attempt > 0:
                alt = self.registry.select(st.capability, exclude=tried_agents)
                if alt is not None:
                    cur_agent = alt
                    tried_agents.append(alt.name)
                    self._monitor.emit(ctx.task_id, "subtask_retry", "dispatcher", {
                        "subtask_id": st.id, "attempt": attempt,
                        "new_agent": cur_agent.name,
                    })
            sem = self._agent_sem(cur_agent.name)
            try:
                async with sem:
                    res = await asyncio.wait_for(cur_agent.handle(st), timeout=st.timeout)
                if res.get("status") == "completed":
                    return res
                last_error = res.get("error")
            except asyncio.TimeoutError:
                last_error = f"执行超时（{st.timeout}s）"
                st.status = SubTaskStatus.TIMEOUT
                self._monitor.emit(ctx.task_id, "subtask_timeout", "dispatcher",
                                   {"subtask_id": st.id, "timeout": st.timeout},
                                   level="WARNING")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                last_error = f"{type(e).__name__}: {e}"

            if attempt < self.retry_policy.max_retries:
                st.retry_count += 1
                self._monitor.metrics.subtask_retried()
                await asyncio.sleep(self.retry_policy.delay(attempt))

        return {"status": "failed", "result": None, "error": last_error}

    def _agent_sem(self, name: str) -> asyncio.Semaphore:
        """获取 Agent 维度信号量，动态注册的 Agent 自动补建。"""
        if name not in self._agent_sems:
            agent = self.registry.get(name)
            cap = agent.max_concurrency if agent else 1
            self._agent_sems[name] = asyncio.Semaphore(cap)
        return self._agent_sems[name]
