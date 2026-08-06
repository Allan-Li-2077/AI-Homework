---
name: fetch-zzz-events
description: 获取绝区零正在进行中的活动信息，保存为HTML到events目录
---

## 执行

运行脚本 `fetch_events.py`：

```bash
python3 skills/fetch-zzz-events/fetch_events.py
```

脚本自动完成：通过SMW API获取结构化活动数据 → 筛选进行中活动 → 生成HTML保存到 `events/YYYY-MM-DD.html`。

## 原理

- **数据源**：B站WIKI Semantic MediaWiki API（`api.php?action=ask`），返回JSON而非HTML页面
- **筛选**：比较 `结束时间` 与当前时间，过期活动自动过滤
- **输出**：深色主题HTML，限时活动 + 永久活动两张表，含名称/时间/剩余时间/版本/标签

## 故障排查

- 网络错误：检查 `wiki.biligame.com` 连通性
- 0 events：API可能变更，检查 `api.php?action=ask` 返回格式
