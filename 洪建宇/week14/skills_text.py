"""两版 weather-query skill 文本，用于 token 消耗对比。

- ORIGINAL_SKILL：详细版（初始版本，字段说明+表格+中英示例+完整 fallback）
- OPTIMIZED_SKILL：精简版（压缩描述、删除冗余、保留必要指令）
"""

# ========================================================================
# 原始版：详细但冗长
# ========================================================================
ORIGINAL_SKILL = """---
name: "weather-query"
description: "Queries current weather conditions for a given location and replies with temperature, weather description, wind, and humidity. Invoke when the user sends a location/city name and asks for weather, or mentions 天气/天气状况/天气预报."
---

# Weather Query

This skill queries real-time weather for a location provided by the user and replies with a concise weather report.

## When to Invoke

- User sends a location (city/district name) and wants to know the weather
- User asks "XX天气怎么样" / "XX天气" / "查天气"
- User mentions 天气状况 / 天气预报 / weather

## How to Use

### Step 1: Extract the location

Identify the location name from the user's message. Acceptable formats:
- Chinese city/district names: 北京, 上海, 深圳, 广州天河区
- English city names: Tokyo, New York, London
- Pinyin: beijing, shanghai

### Step 2: Query the weather

Use the **WebFetch** tool to call the wttr.in API (free, no API key required):

```
https://wttr.in/{location}?format=j1&lang=zh
```

- `format=j1` returns structured JSON data (recommended for parsing)
- `lang=zh` makes text fields return in Chinese

For Chinese location names, URL-encode the location. Example:
```
https://wttr.in/北京?format=j1&lang=zh
```

### Step 3: Parse and reply

Extract the following fields from the JSON response:

| Field | JSON path | Description |
|-------|-----------|-------------|
| 地点 | `nearest_area[0].areaName[0].value` + `nearest_area[0].region[0].value` | Location name |
| 当前温度 | `current_condition[0].temp_C` | Temperature in °C |
| 体感温度 | `current_condition[0].FeelsLikeC` | Feels-like temperature |
| 天气描述 | `current_condition[0].lang_zh[0].value` | Weather in Chinese |
| 风向风速 | `current_condition[0].winddir16Point` + `current_condition[0].windspeedKmph` km/h | Wind info |
| 湿度 | `current_condition[0].humidity` % | Humidity |
| 能见度 | `current_condition[0].visibility` km | Visibility |

### Step 4: Format the reply

Reply in the user's language with a concise, readable format:

**Example reply (Chinese):**

```
📍 北京（北京）
🌡️ 当前温度：15°C（体感 13°C）
🌤️ 天气：晴
💨 风向风速：北风 12 km/h
💧 湿度：45%
👁️ 能见度：10 km
```

**Example reply (English):**

```
📍 Tokyo (Tokyo)
🌡️ Temperature: 18°C (feels like 17°C)
🌤️ Weather: Partly cloudy
💨 Wind: NE 15 km/h
💧 Humidity: 60%
👁️ Visibility: 10 km
```

## Fallback

If wttr.in is unavailable or returns an error:
1. Try the Open-Meteo API instead:
   - Geocoding: `https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=zh`
   - Weather: `https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m`
2. If both fail, tell the user the weather service is temporarily unavailable.

## Notes

- Always use `format=j1` for structured data; do NOT fetch the plain-text HTML page.
- URL-encode non-ASCII location names in the request URL.
- Keep the reply concise; do not include the raw JSON.
- Match the user's language for the reply (Chinese by default).
"""


# ========================================================================
# 优化版：精简指令，保留必要信息
# ========================================================================
OPTIMIZED_SKILL = """---
name: weather-query
description: 查询指定地点的实时天气。触发：用户发送城市/区县名并询问天气，或提到"天气/天气状况/天气预报"。
---

# 天气查询

调用 wttr.in 获取实时天气并简洁回复。

## 流程
1. 从用户消息提取地点（支持中文/英文/拼音，如"北京""Tokyo""shanghai"）。
2. WebFetch 调用：`https://wttr.in/{地点URL编码}?format=j1&lang=zh`
3. 解析 `current_condition[0]`：temp_C、FeelsLikeC、lang_zh[0].value、winddir16Point、windspeedKmph、humidity、visibility。
4. 按用户语言输出（默认中文）：

```
📍 {地点}
🌡️ 温度：{temp_C}°C（体感 {FeelsLikeC}°C）
🌤️ {天气}
💨 {风向}{风速} km/h
💧 湿度：{humidity}%
👁️ 能见度：{visibility} km
```

## 备用
wttr.in 失败时改用 Open-Meteo：先 `geocoding-api.open-meteo.com/v1/search?name={地点}` 取经纬度，再 `api.open-meteo.com/v1/forecast` 取当前数据。仍失败则告知用户暂不可用。

## 约束
- 用 format=j1 取 JSON，不要抓 HTML。
- 非ASCII地点须URL编码。
- 回复简短，不输出原始JSON。
"""

# 用户系统提示：把 skill 列表喂给模型，模拟 TRAE 的 skill 路由
ROUTER_SYSTEM = """你是 skill 路由器。可用 skill 如下：

{skill}

用户发来消息后，请输出 JSON：{"skill":"<skill-name>","location":"<提取的地点>"}。
若不匹配任何 skill，输出 {"skill":"none","location":""}。仅输出 JSON，不要解释。"""
