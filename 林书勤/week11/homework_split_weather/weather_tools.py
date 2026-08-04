"""
weather_tools.py — 天气查询工具拆分实现

核心设计思想：
  将原本的单一 get_weather(city) 函数拆分为两个独立的原子工具：
  
  1. geocode(city): 地理编码
     - 输入：城市名称（中文）
     - 输出：经纬度坐标
     - 用途：独立回答位置查询，或作为天气查询的前置步骤
  
  2. get_weather_by_coords(latitude, longitude): 天气查询
     - 输入：地理坐标
     - 输出：当前天气及未来3天预报
     - 用途：基于已知坐标直接查询天气
  
  设计优势：
    ✓ 单一职责：每个工具专注一个功能
    ✓ 可组合性：输出可直接作为下一工具的输入
    ✓ 独立性：可单独调用提供价值
    ✓ 可测试性：业务逻辑与 LLM 解耦

技术栈：
  - httpx: HTTP 客户端
  - Open-Meteo API: 免费天气数据源（无需 API Key）
"""

import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODE_MAP = {
    0: "晴天", 1: "大致晴朗", 2: "局部多云", 3: "阴天",
    45: "雾", 48: "冻雾",
    51: "小毛毛雨", 53: "中毛毛雨", 55: "大毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "小阵雨", 81: "中阵雨", 82: "大阵雨",
    95: "雷暴", 96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹",
}


def geocode(city: str) -> str:
    """
    地理编码工具：城市名 → 经纬度
    
    功能：
      - 查询城市的地理坐标（纬度、经度）
      - 自动处理同名城市消歧（优先高级行政区）
      - 返回格式化的位置信息
    
    策略：
      1. 首次查询：使用原始城市名
      2. 消歧优化：若结果为低级行政点，尝试"城市名+市"重查
      3. 排序逻辑：优先返回人口最多的高级行政区
    
    示例：
      输入: "宁德"
      输出: "城市：中国 福建省 宁德\n纬度(latitude)：26.66\n经度(longitude)：119.52"
    
    异常处理：
      - 城市未找到时返回友好提示
      - 网络错误时抛出异常供上层处理
    """
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(GEOCODING_URL, params={
            "name": city, "count": 10, "language": "zh", "format": "json",
        })
        resp.raise_for_status()
        results = resp.json().get("results") or []

        # 与原 backend 同样的同名小村庄消歧策略：裸低级行政点且没带"市/县/区"后缀，
        # 就用 city+"市" 重查一次并优先采用。
        def _geocode(name: str):
            r = client.get(GEOCODING_URL, params={
                "name": name, "count": 10, "language": "zh", "format": "json",
            })
            r.raise_for_status()
            return r.json().get("results") or []

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

        def _rank(r):
            fc = str(r.get("feature_code", ""))
            admin_priority = 1 if fc.startswith("PPLA") or fc.startswith("ADM") else 0
            return (admin_priority, r.get("population") or 0)

        loc = max(results, key=_rank)
        lat = loc["latitude"]
        lon = loc["longitude"]
        location_str = f"{loc.get('country', '')} {loc.get('admin1', '')} {loc.get('name', city)}".strip()
        return (
            f"城市：{location_str}\n"
            f"纬度(latitude)：{lat}\n"
            f"经度(longitude)：{lon}"
        )


def get_weather_by_coords(latitude: float, longitude: float) -> str:
    """
    天气查询工具：经纬度 → 天气数据
    
    功能：
      - 查询指定坐标的当前天气状况
      - 提供未来3天的天气预报
      - 包含温度、湿度、风速、降水等详细信息
    
    输入参数：
      latitude:  纬度（范围：-90 到 90）
      longitude: 经度（范围：-180 到 180）
    
    返回数据：
      - 当前天气：天气描述、温度、湿度、风速
      - 未来预报：日期、天气、最高/最低温、降水量
    
    数据源：
      Open-Meteo Forecast API (免费、无需认证)
      时区：Asia/Shanghai
    
    示例：
      输入: latitude=39.9, longitude=116.4
      输出: 北京地区的完整天气报告
    """
    with httpx.Client(timeout=10.0) as client:
        try:
            resp = client.get(WEATHER_URL, params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
                "timezone": "Asia/Shanghai",
                "forecast_days": 3,
            })
            resp.raise_for_status()
        except httpx.RequestError as e:
            return f"天气数据获取失败：{e}"

        data = resp.json()
        cur = data["current"]
        daily = data["daily"]
        weather_desc = WEATHER_CODE_MAP.get(cur["weather_code"], f"代码{cur['weather_code']}")

        lines = [
            f"坐标：{latitude}°N, {longitude}°E",
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


if __name__ == "__main__":
    # 自测：geocode → 拿经纬度 → get_weather_by_coords，手动演示一遍链式调用
    info = geocode("宁德")
    print(info)
    # 从文本里把经纬度抠出来继续查天气（仅自测用，模型链式调用时自己解析）
    import re
    m_lat = re.search(r"纬度.*?：(-?\d+\.?\d*)", info)
    m_lon = re.search(r"经度.*?：(-?\d+\.?\d*)", info)
    if m_lat and m_lon:
        print("\n--- 链式调用：拿上面经纬度查天气 ---")
        print(get_weather_by_coords(float(m_lat.group(1)), float(m_lon.group(1))))
