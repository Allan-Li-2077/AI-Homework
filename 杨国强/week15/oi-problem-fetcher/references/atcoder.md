# AtCoder 拉取详细说明

## HTML 抓取（无 API）

AtCoder 没有公开稳定的题目 API，全部依赖 HTML 抓取。

### 关键 URL

| 用途 | URL |
|------|-----|
| 单题 | `/contests/<contest>/tasks/<task_id>` |
| 比赛任务列表 | `/contests/<contest>/tasks` |

### 关键 DOM 结构

```
<div id="task-statement">
  <section class="part">
    <h3>...</h3>
    <div class="io-style">...</div>  <!-- 描述 -->
    <pre>...</pre>                  <!-- 样例 -->
  </section>
  ...
</div>
```

样例按 section 解析：`Sample Input 1` 配对 `Sample Output 1`，依次累加。

## 已知坑

- **题目语言**：URL 加 `?lang=zh` 出中文版（部分 contest 没有中文）
- **图片**：少量题（如图像题）需保留 `<img>` 标签
- **公式**：MathJax，保留 `\(...\)` / `\[...\]`
- **比赛未开始**：直接抓 `/contests/<contest>/tasks` 返回的是题目列表但 `.part` 内为空；脚本会输出空题面。**必须确认比赛已结束/已开始**

## 题号格式

- 格式：`abc001_a`、`arc100_b`、`agc001_c`
- 字母小写（题目名中显示为 `ABC001 A`）
- 比赛前缀：`abc` (AtCoder Beginner)、`arc` (AtCoder Regular)、`agc` (AtCoder Grand)
