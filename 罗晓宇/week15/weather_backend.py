'''
weather_backend.py — 天气查询后端

两次内部http请求：geocodeing + weather
错误处理直接返回字符串而非抛异常，方便LLM处理

使用方法（作为模块）：
  from weather_backend import get_weather
  print(get_weather("北京"))

依赖：
  pip install httpx
  Open-Meteo API 完全免费，无需注册    
'''

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# Open_Meteo 天气代码 -> 中文描述映射
WEATHER_CODE_MAP = {
    0:"晴", 1:"主要晴朗", 2:"多云", 3:"阴天", 
    45:"雾", 48:"霾", 
    51: "小毛毛雨", 53: "中毛毛雨", 55: "大毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "小阵雨", 81: "中阵雨", 82: "大阵雨",
    95: "雷暴", 96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹",
}

def get_weather(city: str, forecast_days: int = 7) -> str:
    '''
    获取指定位置的天气信息

    Args:
        city: 城市名称，例如 "北京"
        forecast_days: 预报天数，可选7天or16天，默认7天

    Returns:
        包含温度、湿度、风速、天气状况的文字描述
    '''

    with httpx.Client(timeout=10) as client:
        # Step 1：Geocoding — 城市名 → 经纬度
        # 中国地名常有歧义：裸"宁德"会命中西藏那曲市的一个村（PPL），
        # 而宁德时代总部所在的福建宁德是地级市"宁德市"（PPLA2）。
        # 策略：先按用户输入查；若命中的只是低级行政点（feature_code 纯 PPL），
        # 且用户没带"市/县/区"后缀，就用 city+"市" 重查一次并优先采用。
        def _geocode(city_name: str):
            params = {"name": city_name, "count": 10, "language": "zh", "format": "json"}
            resp = client.get(GEOCODE_URL, params=params)
            resp.raise_for_status()
            return resp.json().get("results") or []

        results = _geocode(city)
        # 判断是否命中低级行政点（feature_code 纯 PPL）
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
            return f"未找到城市 '{city}'，请尝试其他写法（如'宁德市'改'宁德'）"

        # 在候选里优先取行政级别更高的（feature_code 含 A = 某级政府驻地），
        # 若行政级别相同，则取人口更多的
        def _rank(r):
            fc = str(r.get("feature_code", ""))
            admin_priority = 1 if fc.startswith("PPLA") or fc.startswith("ADM") else 0
            pop = r.get("population") or 0
            return (admin_priority, pop)

        loc = max(results, key=_rank) 
        lat, lon = loc["latitude"], loc["longitude"]
        city_name = loc.get("name", city)
        country = loc.get("country", "")
        admin1 = loc.get("admin1", "")  # 省/州级行政区

        # Step 2：天气查询
        try:
            weather_resp = client.get(WEATHER_URL, params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
                "timezone": "Asia/Shanghai",
                "forecast_days": forecast_days,
            })
            weather_resp.raise_for_status()
        except httpx.RequestError as e:
            return f"天气数据获取失败：{e}"


        # Step 3：格式化输出
        data = weather_resp.json()
        current = data["current"]
        daily = data["daily"]

        weather_desc = WEATHER_CODE_MAP.get(current["weather_code"], f"代码{current['weather_code']}")
        location_str = f"{country} {admin1} {city_name}".strip()

        lines = [
            f"[{location_str}]天气报告",
            f"坐标：{lat:.2f}°N, {lon:.2f}°E",
            "",
            f"当前天气：{weather_desc}",
            f"  温度：{current['temperature_2m']}°C",
            f"  相对湿度：{current['relative_humidity_2m']}%",
            f"  风速：{current['wind_speed_10m']} km/h",
            "",
            f"未来{forecast_days}天预报：",
        ]
        for i in range(forecast_days):
            day_desc = WEATHER_CODE_MAP.get(daily["weather_code"][i], "")
            lines.append(
                f"  {daily['time'][i]}：{day_desc}，"
                f"{daily['temperature_2m_max'][i]}°C / {daily['temperature_2m_min'][i]}°C，"
                f"降水 {daily['precipitation_sum'][i]} mm"
            )

        return "\n".join(lines)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", required=True)
    args = parser.parse_args()
    print(get_weather(args.city))    