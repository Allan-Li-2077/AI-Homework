"""
weather_backend.py — 天气查询后端（三种方式共享的业务逻辑）

教学重点：
  1. 同样是"纯业务逻辑"，与 rag_backend 平级，被三种方式复用
  2. 原来的 get_weather 内部两次 HTTP 请求（Geocoding + 天气查询），现在拆成两个独立函数：
     - get_city_latAndlon(city) → 城市→经纬度（结构化 JSON）
     - get_weather_by_latlon(lat, lon, city_name) → 经纬度→天气报告
  3. 拆分后，大模型可以自行决策：先调 get_city_latAndlon 获取经纬度，
     再用经纬度调 get_weather_by_latlon——这就是 Function Call 链式调用的教学价值
  4. 错误处理返回可读字符串而非抛异常，方便 LLM 直接消费

使用方式（作为模块）：
  from src.weather_backend import get_city_latAndlon, get_weather_by_latlon
  loc = get_city_latAndlon("宁德")
  print(get_weather_by_latlon(lat=26.66, lon=119.53, city_name="宁德"))

依赖：
  pip install httpx
  Open-Meteo API 完全免费，无需注册
"""

import json

import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo 天气代码 → 中文描述映射
WEATHER_CODE_MAP = {
    0: "晴天", 1: "大致晴朗", 2: "局部多云", 3: "阴天",
    45: "雾", 48: "冻雾",
    51: "小毛毛雨", 53: "中毛毛雨", 55: "大毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "小阵雨", 81: "中阵雨", 82: "大阵雨",
    95: "雷暴", 96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹",
}


# ── 工具一：城市 → 经纬度 ─────────────────────────────────────────────────

def get_city_latAndlon(city: str) -> str:
    """
    查询指定城市的经纬度及地理信息。

    Args:
        city: 城市名称，支持中文，例如 "宁德"、"北京"、"上海"

    Returns:
        JSON 字符串，包含 latitude、longitude、city_name、country、admin1 等字段。
        查询失败时返回错误提示字符串。
    """
    with httpx.Client(timeout=10.0) as client:
        def _geocode(name: str):
            resp = client.get(GEOCODING_URL, params={
                "name": name, "count": 10, "language": "zh", "format": "json",
            })
            resp.raise_for_status()
            return resp.json().get("results") or []

        # 中国地名常有歧义：裸"宁德"会命中西藏那曲市的一个村（PPL），
        # 而宁德时代总部所在的福建宁德是地级市"宁德市"（PPLA2）。
        # 策略：先按用户输入查；若命中的只是低级行政点（feature_code 纯 PPL），
        # 且用户没带"市/县/区"后缀，就用 city+"市" 重查一次并优先采用。
        results = _geocode(city)
        is_low_admin = all(
            str(r.get("feature_code", "")).startswith("PPL")
            and not str(r.get("feature_code", "")).startswith("PPLA")
            for r in results
        ) if results else True
        has_suffix = any(city.endswith(s) for s in ("市", "县", "区", "镇"))
        if is_low_admin and not has_suffix:
            retry = _geocode(city + "市")
            if retry:
                results = retry

        if not results:
            return f"未找到城市 '{city}'，请尝试其他写法（如'宁德'改'宁德市'）"

        # 优先取行政级别更高的（feature_code 含 A = 某级政府驻地），
        # 其次取有人口数据的，避免落到同名小村庄
        def _rank(r):
            fc = str(r.get("feature_code", ""))
            admin_priority = 1 if fc.startswith("PPLA") or fc.startswith("ADM") else 0
            pop = r.get("population") or 0
            return (admin_priority, pop)

        loc = max(results, key=_rank)

        # 返回结构化 JSON，方便大模型提取经纬度传给下一个工具
        return json.dumps({
            "latitude": loc["latitude"],
            "longitude": loc["longitude"],
            "city_name": loc.get("name", city),
            "country": loc.get("country", ""),
            "admin1": loc.get("admin1", ""),
        }, ensure_ascii=False)


# ── 工具二：经纬度 → 天气报告 ───────────────────────────────────────────────

def get_weather_by_latlon(lat: float, lon: float, city_name: str = "") -> str:
    """
    根据经纬度查询当前天气及未来3天预报。

    Args:
        lat:       纬度，例如 26.66
        lon:       经度，例如 119.53
        city_name: 城市名（可选，用于报告标题显示）

    Returns:
        包含温度、湿度、风速、天气状况和3天预报的文字描述
    """
    with httpx.Client(timeout=10.0) as client:
        try:
            weather_resp = client.get(WEATHER_URL, params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
                "timezone": "Asia/Shanghai",
                "forecast_days": 3,
            })
            weather_resp.raise_for_status()
        except httpx.RequestError as e:
            return f"天气数据获取失败：{e}"

        data = weather_resp.json()
        cur = data["current"]
        daily = data["daily"]

        # 格式化输出
        weather_desc = WEATHER_CODE_MAP.get(cur["weather_code"], f"代码{cur['weather_code']}")
        location_str = city_name or f"{lat:.2f}°N, {lon:.2f}°E"

        lines = [
            f"【{location_str}】天气报告",
            f"坐标：{lat:.2f}°N, {lon:.2f}°E",
            "",
            f"当前天气：{weather_desc}",
            f"  温度：{cur['temperature_2m']}°C",
            f"  相对湿度：{cur['relative_humidity_2m']}%",
            f"  风速：{cur['wind_speed_10m']} km/h",
            "",
            "未来3天预报：",
        ]
        for i in range(3):
            day_desc = WEATHER_CODE_MAP.get(daily["weather_code"][i], "")
            lines.append(
                f"  {daily['time'][i]}：{day_desc}，"
                f"{daily['temperature_2m_max'][i]}°C / {daily['temperature_2m_min'][i]}°C，"
                f"降水 {daily['precipitation_sum'][i]} mm"
            )

        return "\n".join(lines)


# ── 兼容旧接口（MCP/CLI 方式可能仍在用 get_weather(city)）───────────────────

def get_weather(city: str) -> str:
    """
    一次性查询：城市→经纬度→天气（内部串联两个工具）。
    保留此函数是为了 MCP/CLI 等方式的兼容调用，
    Function Call 方式请分别调用 get_city_latAndlon + get_weather_by_latlon。
    """
    loc_json = get_city_latAndlon(city)
    try:
        loc = json.loads(loc_json)
    except (json.JSONDecodeError, TypeError):
        # get_city_latAndlon 返回了错误字符串，直接透传
        return loc_json
    return get_weather_by_latlon(
        lat=loc["latitude"],
        lon=loc["longitude"],
        city_name=loc.get("city_name", city),
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("geocode")
    p1.add_argument("--city", required=True)
    p2 = sub.add_parser("weather")
    p2.add_argument("--city", required=True)
    p3 = sub.add_parser("weather-latlon")
    p3.add_argument("--lat", type=float, required=True)
    p3.add_argument("--lon", type=float, required=True)
    p3.add_argument("--city-name", default="")
    args = parser.parse_args()

    if args.cmd == "geocode":
        print(get_city_latAndlon(args.city))
    elif args.cmd == "weather":
        print(get_weather(args.city))
    else:
        print(get_weather_by_latlon(args.lat, args.lon, args.city_name))