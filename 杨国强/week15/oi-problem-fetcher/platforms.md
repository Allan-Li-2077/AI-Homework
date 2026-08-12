# 平台速查表

各 OJ 的 URL 模板、题号格式、首选接口、备选方案。

## 洛谷 (Luogu)

- **首页**：https://www.luogu.com.cn
- **题号格式**：`P<n>` / `B<n>` / `U<n>` / `AT_<contest>_<task>`
- **HTML 页面**：`https://www.luogu.com.cn/problem/<problemId>`
- **API**：`POST https://www.luogu.com.cn/api/problem/detail`，body: `{"problemId":"P1000"}`
- **认证**：公开题不需要；私密/比赛题需要 `LUOGU_COOKIE` 环境变量（值为浏览器中 `_uid` + `client_id` Cookie）
- **限流**：建议 1 req/s，加随机抖动更安全

## Codeforces

- **首页**：https://codeforces.com
- **题号格式**：`<contestId><Letter><Variant?>`（如 `1A`、`1800A`、`1800A2`）
- **HTML 页面**：`https://codeforces.com/problemset/problem/<contestId>/<index>`
- **API**：`GET https://codeforces.com/api/problemset.problems`（全量）或 `GET https://codeforces.com/api/contest.standings?contestId=<id>`（单场）
- **认证**：公开 API 不需要，但加 `?lang=zh` 可拿中文翻译（如有）
- **限流**：API 端 1 req/s，超出会被临时 ban

## AtCoder

- **首页**：https://atcoder.jp
- **题号格式**：`<contest>_<task>`（如 `abc001_a`、`arc100_b`、`agc001_c`）
- **HTML 页面**：`https://atcoder.jp/contests/<contest>/tasks/<task_id>`（如 `/contests/abc001/tasks/abc001_a`）
- **API**：无官方公开 API，依赖 HTML 抓取
- **认证**：否
- **语言**：URL 加 `?lang=en` / `?lang=zh` 控制输出语言
- **整场比赛**：抓 `https://atcoder.jp/contests/<contest>/tasks` 拿到所有题链接

## 牛客 (Nowcoder)

- **首页**：https://www.nowcoder.com
- **题号格式**：`NC<number>`（如 `NC16693`）或题目 ID（数字）
- **HTML 页面**：`https://www.nowcoder.com/practice/<id>`（题目页是 `/practice/` 而非 `/problem/`）
- **API**：部分题目走 `https://www.nowcoder.com/api/question/detail?questionId=<id>`，但返回 JSON 结构不稳定
- **认证**：公开题不需要；带权限题需要 `NOWCODER_COOKIE`
- **限流**：建议 2 req/s

## HDUOJ (HDU)

- **首页**：http://acm.hdu.edu.cn
- **题号格式**：`<number>`（如 `1000`、`2001`），可加 `HDU` 前缀
- **HTML 页面**：`http://acm.hdu.edu.cn/showproblem.php?pid=<number>`
- **API**：无公开 API，依赖 HTML 抓取
- **认证**：否
- **编码**：GBK，脚本需强制 `response.encoding = 'gbk'`
- **整场比赛**：HDU 没有"比赛"概念，按题号区间拉取即可

## 机构 OJ（通用）

任何非上述平台都走 `fetch_generic.py`：

- **输入**：用户传 `--url <problemUrl>`
- **策略**：用 BeautifulSoup 通用清洗，提取 `<title>`、正文、`<pre>` 中的样例
- **要求**：用户必须明确题目的 HTML 结构约定，或同意接受粗糙输出

## 题号 → 平台识别规则（Python 实现参考）

```python
import re

PLATFORM_PATTERNS = [
    ("luogu",     re.compile(r"^(?:P|B|U)\d+$|^AT_\w+$", re.IGNORECASE)),
    ("codeforces",re.compile(r"^\d+[A-Z]\d?$")),
    ("atcoder",   re.compile(r"^[a-z]{2,3}\d{3}[a-z]$", re.IGNORECASE)),
    ("nowcoder",  re.compile(r"^NC\d+$", re.IGNORECASE)),
    ("hduoj",     re.compile(r"^(?:hdu\s*)?\d+$", re.IGNORECASE)),
]

def detect_platform(problem_id: str) -> str:
    s = problem_id.strip()
    for platform, pat in PLATFORM_PATTERNS:
        if pat.match(s):
            # HDU + AtCoder 形如 ABC001 会被 codeforces 模式冲突，atcoder 必须先于 codeforces
            if platform == "codeforces" and re.match(r"^[a-z]{2,3}\d{3}[a-z]$", s, re.IGNORECASE):
                return "atcoder"
            return platform
    return "unknown"
```

> 注意：**AtCoder 的题号形如 `abc001_a`**（小写），不会被 codeforces 模式（`\d+[A-Z]\d?`）误匹配；上面代码仅作演示用，实际以脚本中 `detect_platform` 为准。
