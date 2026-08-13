"""结果聚合与回传模块。

当执行计划中所有子任务到达终态后，收集各子任务结果，按原始任务结构合并组装，
对冲突/重复结果消解去重，对失败子任务降级标注，并生成包含耗时、成功率、
并行度等统计的执行报告。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from ..core.models import ExecutionPlan, SubTask, SubTaskStatus, TaskContext, TaskStatus
from ..monitor import get_monitor


class ResultAggregator:
    """结果聚合器。"""

    def __init__(self, monitor=None) -> None:
        self._monitor = monitor or get_monitor()

    def aggregate(self, ctx: TaskContext) -> Dict[str, Any]:
        """聚合所有子任务结果，生成最终结果与执行报告，回写上下文。"""
        plan = ctx.plan
        self._monitor.emit(ctx.task_id, "aggregate_start", "aggregator", {})

        # 根据执行结果同步子任务状态，确保报告统计与结果一致
        for st in plan.subtasks:
            rstatus = ctx.results.get(st.id, {}).get("status")
            if rstatus == "completed":
                st.status = SubTaskStatus.COMPLETED
            elif rstatus == "failed":
                st.status = SubTaskStatus.FAILED

        final_result = self._assemble_result(ctx, plan)
        report = self._build_report(ctx, plan)

        ctx.report = report
        ctx.final_result = final_result
        any_success = report["success_count"] > 0
        ctx.status = TaskStatus.COMPLETED if any_success else TaskStatus.FAILED

        self._monitor.emit(ctx.task_id, "aggregate_done", "aggregator", {
            "success_count": report["success_count"],
            "failed_count": report["failed_count"],
            "total_duration": report["total_duration"],
            "max_parallelism": report["max_parallelism"],
        })
        return {"final_result": final_result, "report": report}

    # ---- 结果组装 ----
    def _assemble_result(self, ctx: TaskContext, plan: ExecutionPlan) -> Dict[str, Any]:
        """按子任务名称组装最终结果，失败项降级标注。"""
        assembled: Dict[str, Any] = {}
        seen_hashes: Dict[str, str] = {}  # 内容哈希 -> 首个 name

        for st in plan.subtasks:
            res = ctx.results.get(st.id, {})
            if res.get("status") == "completed":
                value = res.get("result")
                # 去重：相同内容标注引用
                try:
                    h = hashlib_of(value)
                except Exception:  # noqa: BLE001
                    h = None
                if h is not None and h in seen_hashes:
                    assembled[st.name] = {
                        "_deduped": True,
                        "_ref": seen_hashes[h],
                    }
                else:
                    assembled[st.name] = value
                    if h is not None:
                        seen_hashes[h] = st.name
            else:
                err = res.get("error") if res else "未执行"
                assembled[st.name] = {
                    "_missing": True,
                    "_error": err or "未知错误",
                    "_capability": st.capability,
                }
        return assembled

    # ---- 执行报告 ----
    def _build_report(self, ctx: TaskContext, plan: ExecutionPlan) -> Dict[str, Any]:
        sub_reports: List[Dict[str, Any]] = []
        for st in plan.subtasks:
            res = ctx.results.get(st.id, {})
            sub_reports.append({
                "name": st.name,
                "capability": st.capability,
                "agent": st.assigned_agent,
                "status": st.status.value,
                "started_at": st.started_at,
                "finished_at": st.finished_at,
                "duration": st.duration,
                "retry_count": st.retry_count,
                "error": res.get("error") if res else None,
            })

        total = len(plan.subtasks)
        success = sum(1 for st in plan.subtasks if st.status == SubTaskStatus.COMPLETED)
        failed = total - success

        starts = [st.started_at for st in plan.subtasks if st.started_at]
        ends = [st.finished_at for st in plan.subtasks if st.finished_at]
        total_duration = (max(ends) - min(starts)) if starts and ends else 0.0
        parallelism = self._max_parallelism(plan.subtasks)

        return {
            "task_id": ctx.task_id,
            "status": ctx.status.value,
            "subtask_count": total,
            "success_count": success,
            "failed_count": failed,
            "success_rate": round(success / total, 4) if total else 0.0,
            "total_duration": round(total_duration, 4),
            "max_parallelism": parallelism,
            "avg_subtask_duration": round(
                sum(st.duration or 0 for st in plan.subtasks) / total, 4
            ) if total else 0.0,
            "subtasks": sub_reports,
        }

    def _max_parallelism(self, subtasks: List[SubTask]) -> int:
        """扫描线计算最大同时运行子任务数（并行度）。"""
        events: List[tuple] = []
        for st in subtasks:
            if st.started_at and st.finished_at:
                events.append((st.started_at, 1))
                events.append((st.finished_at, -1))
        if not events:
            return 0
        events.sort(key=lambda x: (x[0], x[1]))
        cur = peak = 0
        for _, delta in events:
            cur += delta
            peak = max(peak, cur)
        return peak


def hashlib_of(value: Any) -> str:
    """对结果计算稳定哈希，用于去重。"""
    s = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(s.encode("utf-8")).hexdigest()
