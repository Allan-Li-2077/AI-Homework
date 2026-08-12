# 洛谷拉取详细说明

## API 优先 + HTML 回退

主脚本 `scripts/fetch_luogu.py` 先打 API：

```
POST https://www.luogu.com.cn/api/problem/detail
Headers:
  x-luogu-type: content-only
  Referer: https://www.luogu.com.cn/problem/<pid>
Body:
  {"problemId": "P1000"}
```

API 成功时返回结构化 JSON，含 `background` / `description` / `inputFormat` / `outputFormat` / `sampleInput{i}` / `sampleOutput{i}` / `hint` / `limit` / `tags`。

API 失败（鉴权/限流/私密题）时回退到抓 HTML `/problem/<pid>`，但样例可能拿不到。

## 私密题 / 比赛题

需要传 Cookie：

```bash
python fetch_luogu.py --problem T123456 --cookie "_uid=12345; client_id=abcd" --out ./t.md
```

**获取 Cookie 步骤**（浏览器开发者工具）：

1. 打开 https://www.luogu.com.cn 并登录
2. F12 → Network → 任意请求 → 复制 `Cookie` 头
3. 把 Cookie 字符串整体传进 `--cookie`

**安全建议**：私密题 Cookie 不要进 git，可放 `~/.bashrc` 或 `.env`：

```bash
export LUOGU_COOKIE='_uid=...; client_id=...'
```

## 已知坑

- **MathJax 公式**：洛谷用 `\(...\)` 和 `\[...\]`，`clean_html` 会原样保留
- **图片**：通常在 `img.esolang-pic` 中，自动转绝对 URL
- **题号大小写**：P/B/U 必须大写；脚本内部会 `pid.upper()`
- **比赛题号**：`AT_<contest>_<task>`，先走洛谷 API（很多比赛题洛谷有镜像），失败回退 AtCoder 脚本
