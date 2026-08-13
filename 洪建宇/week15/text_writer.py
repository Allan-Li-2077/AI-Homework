"""文本写作 SubAgent。

根据标题、要点列表与风格（report / email / summary）生成结构化 Markdown 文本。
内容基于要点真实展开，不使用占位 TODO。仅使用标准库。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from ..base import BaseSubAgent
from ...core.models import SubTask


def _normalize_points(points: Any) -> List[str]:
    """将 points 规整为非空字符串列表。"""
    if not points:
        return []
    if isinstance(points, str):
        return [points] if points.strip() else []
    if isinstance(points, (list, tuple)):
        return [str(p) for p in points if p is not None and str(p).strip()]
    return [str(points)]


def _write_report(title: str, points: List[str], extra: str) -> str:
    """生成 report 风格：标题 + 概述 + 分点详述 + 结论。"""
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## 概述")
    lines.append(
        f"本报告围绕「{title}」展开，共归纳 {len(points)} 个核心要点，"
        "结合实际场景进行分析并给出结论。"
    )
    lines.append("")
    lines.append("## 分点详述")
    for idx, point in enumerate(points, start=1):
        lines.append(f"### {idx}. {point}")
        lines.append("")
        lines.append(
            f"针对「{point}」，需要明确其关键因素与实施路径：首先梳理现状与目标，"
            "其次评估资源与风险，最后制定可执行的步骤并设定可量化的验收标准，"
            "以确保落地效果可追踪、可复盘。"
        )
        lines.append("")
    if extra:
        lines.append("## 补充说明")
        lines.append(extra)
        lines.append("")
    lines.append("## 结论")
    lines.append(
        "综合以上分析，建议优先推进高价值、低风险的要点，"
        "建立反馈机制持续优化，并在关键节点进行评审以确保整体目标达成。"
    )
    return "\n".join(lines)


def _write_email(title: str, points: List[str], extra: str) -> str:
    """生成 email 风格：称呼 + 正文 + 落款。"""
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("您好，")
    lines.append("")
    if points:
        lines.append("以下是本次需要与您同步的要点：")
        lines.append("")
        for point in points:
            lines.append(f"- {point}")
        lines.append("")
        lines.append("针对上述要点，烦请查阅并在方便时给予反馈，以便后续推进。")
    else:
        lines.append("本邮件用于与您同步相关信息，具体内容如标题所述。")
    lines.append("")
    if extra:
        lines.append(extra)
        lines.append("")
    lines.append("如有疑问，欢迎随时沟通。祝工作顺利！")
    lines.append("")
    lines.append("此致")
    lines.append("敬礼")
    lines.append("")
    lines.append("—— 自动生成")
    return "\n".join(lines)


def _write_summary(title: str, points: List[str], extra: str) -> str:
    """生成 summary 风格：精简摘要。"""
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    if points:
        joined = "；".join(points)
        lines.append(
            f"摘要：{title} 涉及 {len(points)} 个要点——{joined}。"
            "整体来看，各要点相互关联，建议统筹推进以达成预期目标。"
        )
    else:
        lines.append(f"摘要：{title}，暂无具体要点补充。")
    if extra:
        lines.append("")
        lines.append(f"补充：{extra}")
    return "\n".join(lines)


class TextWriterAgent(BaseSubAgent):
    """文本写作 Agent：根据要点与风格生成结构化 Markdown。"""

    def __init__(self, max_concurrency: int = 5) -> None:
        super().__init__(
            name="text_writer_agent",
            capabilities="text_writing",
            max_concurrency=max_concurrency,
        )

    async def process(self, subtask: SubTask) -> Dict[str, Any]:
        # 模拟 IO 让出事件循环，使并行调度可观测（内置 Agent 为纯内存计算）
        await asyncio.sleep(0.1)
        # 容错：input_data 可能为 None 或非 dict
        data = subtask.input_data or {}
        if not isinstance(data, dict):
            data = {"title": str(data)}
        title = str(data.get("title", "未命名文档") or "未命名文档").strip()
        points = _normalize_points(data.get("points", []))
        style = str(data.get("style", "report") or "report").strip().lower()
        extra = str(data.get("extra", "") or "").strip()

        if style == "email":
            content = _write_email(title, points, extra)
        elif style == "summary":
            content = _write_summary(title, points, extra)
        else:
            # 未知风格统一回退为 report
            content = _write_report(title, points, extra)

        # 词数估算：按非空白字符数粗略统计（中文按字、英文按字符）
        word_count = len(content.replace("\n", "").replace(" ", ""))
        return {
            "title": title,
            "style": style,
            "content": content,
            "word_count": word_count,
        }
