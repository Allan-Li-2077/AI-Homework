"""调度 Agent 主入口。

SchedulerAgent 整合任务接收、拆解、并行调度与结果聚合，提供端到端的
复合任务处理能力。同时提供命令行接口（CLI）用于提交任务、查询轨迹与指标。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from .agents.base import BaseSubAgent
from .agents.builtin import create_builtin_agents
from .agents.registry import AgentRegistry
from .core.context import TaskStore
from .core.exceptions import SchedulerError, ValidationError
from .core.models import TaskContext, TaskStatus
from .monitor import get_monitor
from .scheduler.aggregator import ResultAggregator
from .scheduler.decomposer import TaskDecomposer
from .scheduler.dispatcher import ParallelDispatcher, RetryPolicy
from .scheduler.receiver import TaskReceiver

DEFAULT_CONFIG = {
    "max_global_concurrency": 20,
    "default_timeout": 120.0,
    "retry": {"max_retries": 2, "interval": 0.3, "backoff": "fixed", "base": 2.0},
    "health_check_interval": 30,
}


def _load_config(path: Optional[str] = None) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    candidate = path or os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(candidate):
        with open(candidate, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        cfg.update(user_cfg)
    return cfg


class SchedulerAgent:
    """调度 Agent：统一接收复合任务，拆解为子任务并行下发并聚合结果。"""

    def __init__(self, config_path: Optional[str] = None, monitor=None) -> None:
        self.monitor = monitor or get_monitor()
        self.config = _load_config(config_path)
        self.registry = AgentRegistry()
        self.store = TaskStore()
        self.receiver = TaskReceiver(store=self.store, monitor=self.monitor)
        self.decomposer = TaskDecomposer(monitor=self.monitor)
        retry_cfg = self.config.get("retry", {})
        self.retry_policy = RetryPolicy(
            max_retries=retry_cfg.get("max_retries", 2),
            interval=retry_cfg.get("interval", 0.3),
            backoff=retry_cfg.get("backoff", "fixed"),
            base=retry_cfg.get("base", 2.0),
        )
        self.dispatcher = ParallelDispatcher(
            registry=self.registry,
            max_global_concurrency=self.config.get("max_global_concurrency", 20),
            retry_policy=self.retry_policy,
            monitor=self.monitor,
        )
        self.aggregator = ResultAggregator(monitor=self.monitor)
        self._health_task: Optional[asyncio.Task] = None
        self._register_builtins()

    # ---- Agent 管理 ----
    def _register_builtins(self) -> None:
        for agent in create_builtin_agents():
            self.registry.register(agent)

    def register_agent(self, agent: BaseSubAgent) -> None:
        self.registry.register(agent)

    def unregister_agent(self, name: str) -> bool:
        return self.registry.unregister(name)

    def list_agents(self) -> List[Dict[str, Any]]:
        return self.registry.snapshot()

    # ---- 核心流程 ----
    async def run(
        self,
        raw_input: Any,
        mode: str = "auto",
        manual_plan: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """端到端执行：接收 -> 拆解 -> 调度 -> 聚合。"""
        ctx = self.receiver.receive(raw_input)
        # 幂等：若任务已到达终态，直接返回已有结果，不重复执行
        if ctx.status in (TaskStatus.COMPLETED, TaskStatus.FAILED) and ctx.report is not None:
            self.monitor.emit(ctx.task_id, "idempotent_return", "scheduler",
                              {"status": ctx.status.value})
            return {
                "task_id": ctx.task_id,
                "status": ctx.status.value,
                "final_result": ctx.final_result,
                "report": ctx.report,
            }
        if manual_plan:
            self.decomposer.set_manual_plan(ctx, manual_plan)
        await self.decomposer.decompose(ctx)
        await self.dispatcher.execute(ctx, mode=mode)
        result = self.aggregator.aggregate(ctx)
        self.store.update(ctx)
        self.monitor.emit(ctx.task_id, "task_returned", "scheduler", {
            "status": ctx.status.value,
            "success_rate": result["report"]["success_rate"],
        })
        return {
            "task_id": ctx.task_id,
            "status": ctx.status.value,
            "final_result": result["final_result"],
            "report": result["report"],
        }

    def run_sync(self, raw_input: Any, mode: str = "auto",
                 manual_plan: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        return asyncio.run(self.run(raw_input, mode=mode, manual_plan=manual_plan))

    # ---- 查询接口 ----
    def get_task(self, task_id: str) -> Optional[TaskContext]:
        return self.store.get(task_id)

    def get_trace(self, task_id: str) -> List[Dict[str, Any]]:
        return self.monitor.get_trace(task_id)

    def metrics(self) -> Dict[str, Any]:
        return self.monitor.metrics_snapshot()

    def prometheus(self) -> str:
        return self.monitor.render_prometheus()

    # ---- 健康检查 ----
    async def health_check(self) -> Dict[str, str]:
        return await self.registry.heartbeat_all()

    def start_health_check(self, interval: Optional[float] = None) -> None:
        """启动后台健康检查任务（需在事件循环中调用）。"""
        interval = interval or self.config.get("health_check_interval", 30)

        async def _loop():
            while True:
                try:
                    await self.registry.heartbeat_all()
                except Exception as e:  # noqa: BLE001
                    self.monitor.emit("_global", "health_check_error", "scheduler",
                                      {"error": repr(e)}, level="ERROR")
                await asyncio.sleep(interval)

        self._health_task = asyncio.create_task(_loop())

    def stop_health_check(self) -> None:
        if self._health_task:
            self._health_task.cancel()
            self._health_task = None


# ------------------------- CLI -------------------------
def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stderr,
    )


def _cmd_submit(agent: SchedulerAgent, args) -> int:
    if args.json_file:
        with open(args.json_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
    elif args.text:
        raw = args.text
    else:
        print("错误：请通过 --text 或 --json-file 提供任务", file=sys.stderr)
        return 2
    manual = None
    if args.manual_plan:
        with open(args.manual_plan, "r", encoding="utf-8") as f:
            manual = json.load(f)
    try:
        result = agent.run_sync(raw, mode=args.mode, manual_plan=manual)
    except ValidationError as e:
        print(json.dumps({"error": e.code, "message": e.message}, ensure_ascii=False))
        return 1
    except SchedulerError as e:
        print(json.dumps({"error": "scheduler_error", "message": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def _cmd_trace(agent: SchedulerAgent, args) -> int:
    trace = agent.get_trace(args.task_id)
    print(json.dumps(trace, ensure_ascii=False, indent=2, default=str))
    return 0


def _cmd_metrics(agent: SchedulerAgent, args) -> int:
    print(json.dumps(agent.metrics(), ensure_ascii=False, indent=2, default=str))
    return 0


def _cmd_agents(agent: SchedulerAgent, args) -> int:
    print(json.dumps(agent.list_agents(), ensure_ascii=False, indent=2, default=str))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="parallel-agent",
        description="多智能体并行任务调度系统",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    parser.add_argument("--config", help="配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    p_submit = sub.add_parser("submit", help="提交复合任务")
    p_submit.add_argument("--text", help="自然语言任务描述")
    p_submit.add_argument("--json-file", help="JSON 任务文件路径")
    p_submit.add_argument("--manual-plan", help="手动拆解方案 JSON 文件")
    p_submit.add_argument("--mode", default="auto",
                          choices=["auto", "parallel", "pipeline"], help="下发模式")
    p_submit.set_defaults(func=_cmd_submit)

    p_trace = sub.add_parser("trace", help="查询任务执行轨迹")
    p_trace.add_argument("task_id")
    p_trace.set_defaults(func=_cmd_trace)

    p_metrics = sub.add_parser("metrics", help="查看系统指标")
    p_metrics.set_defaults(func=_cmd_metrics)

    p_agents = sub.add_parser("agents", help="查看已注册 SubAgent")
    p_agents.set_defaults(func=_cmd_agents)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    agent = SchedulerAgent(config_path=args.config)
    return args.func(agent, args)


if __name__ == "__main__":
    sys.exit(main())
