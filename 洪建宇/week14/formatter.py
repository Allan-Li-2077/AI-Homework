"""天气结果格式化输出模块。

支持两种格式：
- 默认：带 emoji 的多行人类可读文本
- JSON：便于程序解析的紧凑 JSON
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Literal

from .weather import WeatherResult


def format_weather(
    result: WeatherResult,
    fmt: Literal["text", "json"] = "text",
) -> str:
    """把 WeatherResult 转为指定格式的字符串。

    :param result: 天气查询结果
    :param fmt: "text" 多行可读文本（默认）；"json" 紧凑 JSON
    """
    if fmt == "json":
        return json.dumps(asdict(result), ensure_ascii=False)

    # text 格式：与 SKILL.md 中的示例保持一致
    lines = [
        f"📍 {result.location}",
        f"🌡️ 当前温度：{result.temperature}（体感 {result.feels_like}）",
        f"🌤️ 天气：{result.description}",
        f"💨 风向风速：{result.wind}",
        f"💧 湿度：{result.humidity}",
        f"👁️ 能见度：{result.visibility}",
        f"🔎 数据来源：{result.source}",
    ]
    return "\n".join(lines)
