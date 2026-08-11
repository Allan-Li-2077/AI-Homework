---
name: oi-problem-fetcher
description: Pull original OI/ACM contest problems (with sample I/O) from Luogu, institutional OJs, Codeforces, AtCoder, Nowcoder, and HDUOJ by problem ID or ID range. Use when the user mentions "拉题", "拉取题目", "出题", "下载题目", "题目本地化", "P1000", "P1000-P1010", "ABC001 A", "Codeforces 1800A", "HDU 1000", "牛客 题号", or asks to save contest problems as Markdown for classroom handouts.
---

# OI Problem Fetcher

拉取信奥赛/ACM 竞赛原题（含样例输入输出）并输出为 Markdown 文件，供出卷、布置作业、复盘使用。

## 适用场景

- **拉单题**：指定某个题号（如 `P1000`）拉取单题
- **拉区间**：批量拉取一段连续题号（如 `P1000-P1010`、`HDU 1000-1010`）
- **拉比赛整套**：CF 按 contest id、AtCoder 按 contest code 拉整场比赛所有题
- **拉机构 OJ 题**：传入基础 URL + 题号即可

## 不适用

- 需要题解 / 题解视频 / 官方代码 → 见 [references/luogu.md](references/luogu.md) 的扩展方案
- 需要提交评测 → 本 Skill 只做"拉"，不做"评"
- 洛谷已登录 Cookie 的私密题目 → 见下文"鉴权"小节

## 工作流

按这个 checklist 执行：

```
Task Progress:
- [ ] Step 1: 解析用户输入，识别平台与题号
- [ ] Step 2: 选择对应平台的拉取脚本
- [ ] Step 3: 执行脚本，输出 Markdown 文件
- [ ] Step 4: 验证输出文件（题数、样例齐全）
- [ ] Step 5: 告知用户输出位置
```

### Step 1: 解析输入

用户输入通常长这样：

| 形式 | 示例 | 平台 |
|------|------|------|
| `P<number>` / `B<number>` / `U<number>` | `P1000`、`B2001`、`U123` | 洛谷 |
| `AT_<contest>_<task>` | `AT_abc001_a` | 洛谷/AtCoder |
| `<contestId><Letter>`（CF） | `1A`、`1800A`、`1800A2` | Codeforces |
| `HDU <number>` / `hdu<number>` | `HDU 1000`、`hdu1000` | HDUOJ |
| 牛客题号（多为数字 ID） | `NC16693`、`NC200001` | 牛客 |
| `<baseUrl> <id>`（任意 OJ） | `https://example.oj/problem?id=123` | 机构 OJ |

**注意大小写不敏感**：用户输入 `p1000` 和 `P1000` 等价，脚本内部统一转大写 P 系列 / 转小写 HDU 系列。

如果输入含糊（如"帮我拉洛谷第一题"），**必须先确认题号**再继续 —— 不要猜测。

### Step 2: 选择脚本

根据平台选择 `scripts/fetch_<platform>.py`，所有脚本共享 `scripts/common.py` 中的通用工具。

**平台识别优先级**（按下面顺序匹配，命中即停）：

1. 含 `P`/`B`/`U` 前缀后跟数字 → Luogu
2. 含 `AT_` 前缀 → 先 Luogu，404 则回退 AtCoder
3. 含数字+大写字母（如 `1800A`、`1A2`）且是纯字母数字 → Codeforces
4. 含 `HDU`/`hdu` 前缀 → HDUOJ
5. 含 `NC` 前缀数字 → Nowcoder
6. 用户明确给出 URL → 通用抓取器 `scripts/fetch_generic.py`
7. 无法识别 → 询问用户

完整 URL 模板和接口规范见 [platforms.md](platforms.md)。

### Step 3: 执行脚本

**核心调用格式**：

```bash
# 拉单题
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_luogu.py --problem P1000 --out ./problems/P1000.md

# 拉区间（支持步进）
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_luogu.py --range P1000-P1010 --out ./problems/

# 拉 CF 整场比赛
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_codeforces.py --contest 1800 --out ./problems/cf1800/

# 拉 AtCoder 整套
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_atcoder.py --contest abc001 --out ./problems/abc001/

# 通用抓取（机构 OJ）
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_generic.py --url https://oj.xxx.ac.cn/problem?id=123 --out ./problems/prob123.md
```

**推荐工作目录**：在某个题库项目下执行（参见下方"项目化使用"），输出路径用相对路径更稳。

### Step 4: 验证输出

每个脚本都会打印：

```
Fetched P1000 -> ./problems/P1000.md
  ✓ Title: A+B Problem
  ✓ Description: 2 paragraphs
  ✓ Samples: 3 input/output pairs
  ✓ Tags: [入门, 数学]
```

如果某项标 `✗`，应回退到 `platforms.md` 中该平台的 fallback 章节，或提示用户手工补齐。

### Step 5: 告知用户

回复时给出：
1. 输出文件的**绝对路径列表**
2. **题数统计**（成功 / 失败）
3. **失败题目**的清单（如有），并提示对应平台的鉴权 / 网络问题

## 输出格式

每个题目一个 `.md` 文件，统一模板见 [output-template.md](output-template.md)。要点：

- 文件名优先用 `{题号}.md`（如 `P1000.md`），多题时用目录包一层
- 必须包含：标题、原题描述（Markdown 格式保留）、样例输入/样例输出
- 图片 / 公式 / 数学符号：保留 HTML 标签（如 LaTeX 用 `\(...\)`），并在脚本日志里标"含 N 张图需手工补"

## 鉴权

| 平台 | 是否需要登录 | 处理方式 |
|------|--------------|----------|
| 洛谷（公开题） | 否 | 直接抓 |
| 洛谷（私密/比赛题） | 是 | 需要 `LUOGU_COOKIE` 环境变量；详见 [references/luogu.md](references/luogu.md) |
| Codeforces | 否 | 公开 API |
| AtCoder | 否 | 公开 HTML |
| 牛客 | 部分题目需要登录 | 需要 `NOWCODER_COOKIE` 环境变量 |
| HDUOJ | 否 | 公开 |
| 机构 OJ | 看情况 | 通用抓取器允许用户传 `--cookie` |

**鉴权失败的处理**：脚本不报错崩溃，而是回退到"只拿到部分内容"并在日志里标 ⚠️，提示用户手动补充。

## 项目化使用（推荐）

建立一个 `problems-repo` 项目（任何路径都行）作为拉题的工作区：

```
problems-repo/
├── README.md              # 说明本目录的用途
├── problems/              # 题目按平台分目录
│   ├── luogu/
│   ├── codeforces/
│   ├── atcoder/
│   ├── nowcoder/
│   └── hduoj/
├── contests/              # 整场比赛拉取到这里
│   ├── cf-round-1800/
│   └── abc001/
└── .cursor/
    └── skills/            # 把本 Skill 软链或拷贝到这里
```

**首次初始化**：

```bash
mkdir -p problems-repo/problems problems-repo/contests
# 把 Skill 链接进项目（让 Agent 在该项目里也能识别）
ln -s ~/.cursor/skills/oi-problem-fetcher .cursor/skills/
```

之后用户在该项目下说"拉 P1000-P1010"，Agent 会自动用本 Skill 并把文件输出到 `problems/luogu/`。

## 失败模式

| 现象 | 原因 | 解决 |
|------|------|------|
| HTTP 403 | 平台风控 / 缺 Cookie | 见"鉴权"小节 |
| HTML 解析出空题面 | 平台改版、选择器失效 | 去 [references/<platform>.md](references/) 看最新选择器，或手工补 |
| 图片 / 公式丢失 | 部分 OJ 用 MathJax 渲染 | 用 `--render-math` 标记，提示用户手工核对 |
| 区间拉取中途失败 | 网络抖动 | 加 `--retry 3 --retry-delay 5` |
| 题目是付费/私密 | 平台限制 | 诚实告知用户，不绕过 |

## 依赖安装

执行拉取前确保 Python 依赖已装：

```bash
pip install requests beautifulsoup4 lxml html2text
```

可选（如要渲染 LaTeX 公式）：

```bash
pip install markdownify markdown
```

## 自定义扩展

如果用户要求加新平台，按下面模式扩展（参考 [references/](references/) 里现有平台的写法）：

1. 在 `scripts/` 下加 `fetch_<platform>.py`
2. 在 `platforms.md` 加平台速查行
3. 在 `references/` 下加详细文档
4. 复用 `common.py` 的 `clean_html`、`render_markdown`、`write_problem_file` 三个函数即可

## 速查：常用拉题指令

| 用户说 | Agent 做 |
|--------|----------|
| "帮我把洛谷 P1000 到 P1010 拉下来" | `--range P1000-P1010` |
| "把 CF round 1800 整场拉下来" | `--contest 1800` |
| "拉一下 ABC001 的所有题" | `--contest abc001` |
| "HDU 1000 到 1005 帮我下一下" | `--range HDU 1000-1005` |
| "拉一下牛客 NC16693" | `--problem NC16693` |
| "把这个 OJ 的题拉一下 <URL>" | `--url <URL>` |
| "按题号拉完后整理成一份试卷" | 拉完后用 `pandoc` / `markdown-pdf` 合成单文件 |

## Additional Resources

- [platforms.md](platforms.md) — 各平台 URL/API/题号格式速查
- [output-template.md](output-template.md) — 输出 Markdown 模板
- [references/luogu.md](references/luogu.md) — 洛谷详细拉取说明
- [references/codeforces.md](references/codeforces.md) — CF 详细拉取说明
- [references/atcoder.md](references/atcoder.md) — AtCoder 详细拉取说明
- [references/nowcoder.md](references/nowcoder.md) — 牛客详细拉取说明
- [references/hduoj.md](references/hduoj.md) — HDUOJ 详细拉取说明
