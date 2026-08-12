# Codeforces 拉取详细说明

## 两种拉取策略

### 1. 整场比赛（推荐）

```
GET https://codeforces.com/api/contest.standings?contestId=<id>&lang=en
```

返回 JSON 含：
- `result.problems[]`：所有题（index, name, rating, tags）
- `result.rows[]`：所有提交记录

> 注意：`rows` 不含样例，**样例必须单独走 HTML 抓取**（脚本自动处理）。

### 2. 单题 / 字母区间

走 HTML：`https://codeforces.com/problemset/problem/<contestId>/<index>`

- 题面在 `.problem-statement`
- 样例在 `.sample-test`，每个含 `.input pre` 和 `.output pre`

## 限流与反爬

- 1 req/s 安全阈值
- 连续高频请求会被临时 ban（30min 内）
- 脚本默认 `--delay 1.2`

## 中文题面

加 `&lang=zh` 参数（部分题官方有中文翻译，但覆盖率不高）。

```bash
python fetch_codeforces.py --contest 1800 --out ./cf1800/  # 脚本不支持 lang 参数（先这样，需要时改）
```

> 当前脚本默认 `lang=en`，需要中文版时改脚本中 `fetch_contest(contest_id, lang="zh")`。

## 比赛列表查询

CF 没有直接给出"我打过哪些比赛"的 API，但 `codeforces.com/contests` HTML 可爬。如需全比赛列表，可写额外脚本（不在本 Skill 范围内）。
