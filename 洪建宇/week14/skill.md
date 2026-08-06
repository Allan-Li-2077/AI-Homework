name	weather-query
description	查询指定地点的实时天气。触发：用户发送城市/区县名并询问天气，或提到"天气/天气状况/天气预报"。
天气查询
调用 wttr.in 获取实时天气并简洁回复。

流程
从用户消息提取地点（支持中文/英文/拼音，如"北京""Tokyo""shanghai"）。
WebFetch 调用：https://wttr.in/{ 地点URL编码}?format=j1&lang=zh
解析 current_condition[0]：temp_C、FeelsLikeC、lang_zh[0].value、winddir16Point、windspeedKmph、humidity、visibility。
按用户语言输出（默认中文）：

Plain Text

📍 {地点}
🌡️ 温度：{temp_C}°C（体感 {FeelsLikeC}°C）
🌤️ {天气}
💨 {风向}{风速} km/h
💧 湿度：{humidity}%
👁️ 能见度：{visibility} km
备用
wttr.in 失败时改用 Open-Meteo：先 geocoding-api.open-meteo.com/v1/search?name={地点} 取经纬度，再 api.open-meteo.com/v1/forecast 取当前数据。仍失败则告知用户暂不可用。

约束
用 format=j1 取 JSON，不要抓 HTML。
非ASCII地点须URL编码。
回复简短，不输出原始JSON。
