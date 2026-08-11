"""天气查询核心模块。

主数据源：wttr.in（免费、无需 API key、支持中文城市名）
备用数据源：Open-Meteo（wttr.in 不可用时自动切换）
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional


class QueryError(Exception):
    """天气查询失败时抛出。"""


@dataclass
class WeatherResult:
    """统一的天气查询结果。"""

    location: str          # 地点名称
    temperature: str       # 当前温度，带 °C 单位
    feels_like: str        # 体感温度，带 °C 单位
    description: str       # 天气描述
    wind: str             # 风向风速
    humidity: str         # 湿度，带 %
    visibility: str       # 能见度，带 km 单位
    source: str           # 数据来源：wttr.in / open-meteo


# Open-Meteo 天气代码 -> 中文描述
_WMO_CODE_ZH = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "有雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "强阵雨", 82: "暴雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹",
}

# 16 方位风向英文 -> 中文
_WIND_DIR_ZH = {
    "N": "北风", "NNE": "北东北风", "NE": "东北风", "ENE": "东东北风",
    "E": "东风", "ESE": "东东南风", "SE": "东南风", "SSE": "南东南风",
    "S": "南风", "SSW": "南西南风", "SW": "西南风", "WSW": "西西南风",
    "W": "西风", "WNW": "西西北风", "NW": "西北风", "NNW": "北西北风",
}


class WeatherService:
    """天气查询服务，封装主/备数据源调用。"""

    WTTR_BASE = "https://wttr.in"
    OPEN_METEO_GEO = "https://geocoding-api.open-meteo.com/v1/search"
    OPEN_METEO_WEATHER = "https://api.open-meteo.com/v1/forecast"
    REQUEST_TIMEOUT = 10  # 秒

    def query(self, location: str) -> WeatherResult:
        """查询指定地点的当前天气。

        依次尝试 wttr.in、Open-Meteo；全部失败时抛出 QueryError。
        """
        if not location or not location.strip():
            raise QueryError("位置不能为空")

        location = location.strip()
        try:
            return self._query_wttr(location)
        except Exception as exc:
            # 主源失败，降级到备用源
            try:
                return self._query_open_meteo(location)
            except Exception as fallback_exc:
                raise QueryError(
                    f"天气查询失败：{exc}；备用源同样失败：{fallback_exc}"
                ) from fallback_exc

    # ---------------- 主数据源：wttr.in ----------------

    def _query_wttr(self, location: str) -> WeatherResult:
        url = f"{self.WTTR_BASE}/{urllib.parse.quote(location)}?format=j1&lang=zh"
        data = self._fetch_json(url)
        if "current_condition" not in data:
            raise QueryError(f"wttr.in 返回数据异常：{data}")

        current = data["current_condition"][0]
        area = data.get("nearest_area", [{}])[0]
        area_name = area.get("areaName", [{"value": location}])[0]["value"]
        region = area.get("region", [{"value": ""}])[0]["value"]
        full_location = f"{area_name}（{region}）" if region else area_name

        wind_dir_en = current.get("winddir16Point", "")
        wind_dir = _WIND_DIR_ZH.get(wind_dir_en, wind_dir_en)
        wind_speed = current.get("windspeedKmph", "?")
        # 天气描述优先取中文翻译
        desc_zh_list = current.get("lang_zh", [])
        description = desc_zh_list[0]["value"] if desc_zh_list else current.get(
            "weatherDesc", [{"value": "未知"}]
        )[0]["value"]

        return WeatherResult(
            location=full_location,
            temperature=f"{current.get('temp_C', '?')}°C",
            feels_like=f"{current.get('FeelsLikeC', '?')}°C",
            description=description,
            wind=f"{wind_dir} {wind_speed} km/h",
            humidity=f"{current.get('humidity', '?')}%",
            visibility=f"{current.get('visibility', '?')} km",
            source="wttr.in",
        )

    # ---------------- 备用数据源：Open-Meteo ----------------

    def _query_open_meteo(self, location: str) -> WeatherResult:
        lat, lon, display_name = self._geocode(location)
        weather = self._fetch_weather(lat, lon)

        code = weather.get("weather_code", -1)
        description = _WMO_CODE_ZH.get(code, f"代码 {code}")
        wind_speed = weather.get("wind_speed_10m", "?")

        return WeatherResult(
            location=display_name,
            temperature=f"{weather.get('temperature_2m', '?')}°C",
            # Open-Meteo 当前数据无体感温度，使用实际温度代替
            feels_like=f"{weather.get('temperature_2m', '?')}°C",
            description=description,
            wind=f"{wind_speed} km/h",
            humidity=f"{weather.get('relative_humidity_2m', '?')}%",
            # Open-Meteo 当前数据无单独能见度字段（需 visibility 模块），用 - 表示
            visibility="-",
            source="open-meteo",
        )

    def _geocode(self, location: str) -> tuple[float, float, str]:
        params = urllib.parse.urlencode(
            {"name": location, "count": 1, "language": "zh", "format": "json"}
        )
        data = self._fetch_json(f"{self.OPEN_METEO_GEO}?{params}")
        results = data.get("results")
        if not results:
            raise QueryError(f"未找到地点：{location}")
        first = results[0]
        return float(first["latitude"]), float(first["longitude"]), first["name"]

    def _fetch_weather(self, lat: float, lon: float) -> dict:
        params = urllib.parse.urlencode(
            {
                "latitude": lat,
                "longitude": lon,
                "current": (
                    "temperature_2m,relative_humidity_2m,"
                    "weather_code,wind_speed_10m"
                ),
            }
        )
        data = self._fetch_json(f"{self.OPEN_METEO_WEATHER}?{params}")
        if "current" not in data:
            raise QueryError(f"Open-Meteo 返回数据异常：{data}")
        return data["current"]

    # ---------------- 网络请求工具 ----------------

    def _fetch_json(self, url: str) -> dict:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "weather-query-cli/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
