"""数据分析 SubAgent。

对记录列表做统计分析（均值/最大/最小/总和/计数/中位数/标准差），支持按指定字段分组，
并生成纯文本 ASCII 柱状图。仅使用标准库 statistics 模块，无第三方依赖。
"""
from __future__ import annotations

import asyncio
import statistics
from typing import Any, Dict, List, Optional

from ..base import BaseSubAgent
from ...core.models import SubTask


# 默认统计指标
DEFAULT_METRICS = ["mean", "max", "min", "sum", "count"]


def _to_number(value: Any) -> Optional[float]:
    """尝试将值转为 float，失败返回 None（布尔值不计入数值）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _detect_value_field(
    records: List[Dict[str, Any]], preferred: str = "value"
) -> Optional[str]:
    """检测用于数值统计的字段，优先使用 preferred，否则取首个含数值的字段。"""
    if not records:
        return None
    # 优先检查首选字段是否含数值
    if preferred and any(
        isinstance(r, dict) and _to_number(r.get(preferred)) is not None for r in records
    ):
        return preferred
    # 收集字段并保留出现顺序
    ordered_keys: List[str] = []
    seen = set()
    for r in records:
        if isinstance(r, dict):
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    ordered_keys.append(k)
    # 取首个含数值的字段
    for k in ordered_keys:
        if any(isinstance(r, dict) and _to_number(r.get(k)) is not None for r in records):
            return k
    return None


def _compute_stats(values: List[float], metrics: List[str]) -> Dict[str, Any]:
    """根据指定 metrics 计算统计量。"""
    result: Dict[str, Any] = {}
    if not values:
        for m in metrics:
            result[m] = 0 if m == "count" else None
        return result
    for m in metrics:
        if m == "mean":
            result[m] = round(statistics.mean(values), 4)
        elif m == "max":
            result[m] = round(max(values), 4)
        elif m == "min":
            result[m] = round(min(values), 4)
        elif m == "sum":
            result[m] = round(sum(values), 4)
        elif m == "count":
            result[m] = len(values)
        elif m == "median":
            result[m] = round(statistics.median(values), 4)
        elif m == "stdev":
            # 样本标准差至少需要 2 个数据点
            result[m] = round(statistics.stdev(values), 4) if len(values) >= 2 else 0.0
    return result


def _ascii_chart(labels: List[str], values: List[float], max_width: int = 40) -> str:
    """生成纯文本 ASCII 柱状图，每行一个类别，'|' 按数值比例填充。"""
    if not labels:
        return "(无数据)"
    max_val = max(values) if values else 0
    lines: List[str] = []
    for label, val in zip(labels, values):
        if max_val > 0:
            bar_len = max(1, int(round(val / max_val * max_width)))
        else:
            bar_len = 0
        bar = "|" * bar_len
        lines.append(f"{str(label):<16} {bar} {round(float(val), 2)}")
    return "\n".join(lines)


class DataAnalyzerAgent(BaseSubAgent):
    """数据分析 Agent：统计计算 + 分组 + ASCII 柱状图。"""

    def __init__(self, max_concurrency: int = 5) -> None:
        super().__init__(
            name="data_analyzer_agent",
            capabilities="data_analysis",
            max_concurrency=max_concurrency,
        )

    async def process(self, subtask: SubTask) -> Dict[str, Any]:
        # 模拟 IO 让出事件循环，使并行调度可观测（内置 Agent 为纯内存计算）
        await asyncio.sleep(0.1)
        # 容错：input_data 可能为 None 或非 dict
        data = subtask.input_data or {}
        if not isinstance(data, dict):
            data = {"records": []}
        records = data.get("records", [])
        if not isinstance(records, list):
            records = []
        group_by = data.get("group_by")
        group_by = str(group_by).strip() if group_by else None
        metrics = data.get("metrics")
        if not isinstance(metrics, list) or not metrics:
            metrics = list(DEFAULT_METRICS)
        else:
            metrics = [str(m) for m in metrics if m]

        # 空记录：返回合理空结果而非报错
        if not records:
            empty_overall = {m: (0 if m == "count" else None) for m in metrics}
            return {
                "total_records": 0,
                "overall": empty_overall,
                "groups": {},
                "ascii_chart": "(无数据)",
                "metrics_used": metrics,
            }

        value_field = _detect_value_field(records)
        if value_field is None:
            # 未检测到数值字段：仅返回计数与空统计
            empty_overall = {m: (len(records) if m == "count" else None) for m in metrics}
            return {
                "total_records": len(records),
                "overall": empty_overall,
                "groups": {},
                "ascii_chart": "(未检测到数值字段，无法生成柱状图)",
                "metrics_used": metrics,
            }

        # 整体统计：收集所有记录中该字段的数值
        all_values: List[float] = [
            v for v in (
                _to_number(r.get(value_field))
                for r in records if isinstance(r, dict)
            ) if v is not None
        ]
        overall = _compute_stats(all_values, metrics)

        # 分组统计
        groups: Dict[str, Dict[str, Any]] = {}
        if group_by:
            grouped: Dict[str, List[float]] = {}
            for r in records:
                if not isinstance(r, dict):
                    continue
                key = str(r.get(group_by, "unknown"))
                val = _to_number(r.get(value_field))
                if val is None:
                    continue
                grouped.setdefault(key, []).append(val)
            for key, vals in grouped.items():
                groups[key] = _compute_stats(vals, metrics)

        # 生成 ASCII 柱状图：有分组时按组均值，否则按每条记录
        if groups:
            chart_labels = list(groups.keys())
            chart_values = [float(g.get("mean") or 0) for g in groups.values()]
        else:
            chart_labels: List[str] = []
            chart_values: List[float] = []
            for i, r in enumerate(records):
                if not isinstance(r, dict):
                    continue
                label = r.get("name")
                if label is None:
                    label = f"item-{i}"
                chart_labels.append(str(label))
                chart_values.append(float(_to_number(r.get(value_field)) or 0))
        ascii_chart = _ascii_chart(chart_labels, chart_values)

        return {
            "total_records": len(records),
            "overall": overall,
            "groups": groups,
            "ascii_chart": ascii_chart,
            "metrics_used": metrics,
        }
