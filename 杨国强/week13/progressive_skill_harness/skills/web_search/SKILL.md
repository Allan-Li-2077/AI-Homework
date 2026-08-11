---
name: web_search
version: 1.0.0
description: 联网搜索最新信息（演示版：模拟搜索结果，并引导用户接入真实 API）
keywords: [搜索, search, 联网, 最新, 新闻, 网上, 查一下, 找资料]
triggers: [latest_news, real_time_query, web_search_request]
execution: prompt
parameters:
  - name: query
    type: string
    required: true
    description: 搜索关键词或问题
  - name: recency
    type: string
    required: false
    description: 时效性：day / week / month / any（默认 week）
  - name: sources
    type: string
    required: false
    description: 来源偏好：news（新闻）/ academic（学术）/ general（综合）
---

# Web Search Skill

⚠️ **演示版 Skill**：当前 harness **未连接真实搜索引擎**，此 skill 会：
1. 让 LLM 基于自身知识给出一个"看起来像搜索结果"的回答
2. 同时**明确告诉用户这是演示数据**，避免误导

生产环境推荐接入：Tavily / Bing Search / Serper / Brave Search API。

## 输入参数
- 搜索关键词：`{{query}}`
- 时效性：`{{recency | default:week}}`
- 来源偏好：`{{sources | default:general}}`

## 处理流程

### Step 1：分析查询意图
- 这是事实型（"X 是什么"）还是时效型（"X 最新动态"）？
- 是否包含多个子问题？
- 时效性需求：`{{recency}}` 对应的时间窗口

### Step 2：构造"伪搜索结果"
按以下格式模拟 N 条（建议 3~5 条）搜索结果：

```
[1] <标题>
来源：<域名（如 example.com）>
时间：<YYYY-MM-DD>
摘要：<2~3 句话，包含"搜索词"相关关键词>
URL：https://...

[2] ...
```

### Step 3：基于"结果"总结
综合上面的结果，给用户一个**直接可用的回答**（不是搜索列表本身）。

### Step 4：诚实标注
**必须**在结尾加一行：
> ⚠️ 本结果由 LLM 模拟生成，未接入真实搜索 API。生产环境请配置 `WEB_SEARCH_API_KEY`。

## 输出格式

```
## 搜索结果（演示数据）

[1] ...
[2] ...
[3] ...

## 综合回答

<直接回答用户问题的内容>

---
⚠️ 本结果由 LLM 模拟生成，未接入真实搜索 API。
```

## 注意事项
1. **绝不假装是真实数据**：明确标注演示性质
2. **不要编造过于具体的数字**：如"A 公司 2026 年营收增长 37.2%"这种应该避免或标注为"估算"
3. **时效性诚实**：超过知识截止日期的内容明确说"截至我知识库时间（YYYY-MM）为..."
4. **URL 格式正确但内容为占位**：不要写出实际不存在的精确 URL（如 `?id=12345` 这种）