---
name: oi-problem-fetcher
description: Pull original OI/ACM contest problems (with sample I/O) from Luogu, institutional OJs, Codeforces, AtCoder, Nowcoder, and HDUOJ by problem ID or ID range. Supports single-platform single-problem, single-platform batch, multi-platform parallel fetches (via subagent dispatch), and full contest pulls. Use when the user mentions "拉题", "拉取题目", "出题", "下载题目", "题目本地化", "批量拉", "并行拉", "同时拉", "多平台", "一口气", "P1000", "P1000-P1010", "ABC001 A", "Codeforces 1800A", "HDU 1000", "牛客 题号", or asks to save contest problems as Markdown for classroom handouts.
---

# OI Problem Fetcher

拉取信奥赛/ACM 竞赛原题（含样例输入输出）并输出为 Markdown 文件，供出卷、布置作业、复盘使用。

## 何时用本 Skill

**核心触发**：用户说"拉题 / 出题 / 下载题目 / 题目本地化"，并提到任意一个题号或平台。

**进阶触发**：用户提"批量" / "并行" / "同时" / "多平台" / "一口气" 时，**必须触发本 Skill 的 Subagent 并行调度**（见下文"路 B"）。

## 适用场景

- **拉单题**：指定某个题号（如 `P1000`）拉取单题
- **拉区间**：批量拉取一段连续题号（如 `P1000-P1010`、`HDU 1000-1010`）
- **拉比赛整套**：CF 按 contest id、AtCoder 按 contest code 拉整场比赛所有题
- **拉机构 OJ 题**：传入基础 URL + 题号即可
- **多平台并行**：同时拉洛谷 P1000 + CF 1800A + ABC001_a + HDU 1000 → 走 **Subagent 并行调度**

## 不适用

- 需要题解 / 题解视频 / 官方代码 → 见 [references/luogu.md](references/luogu.md) 的扩展方案
- 需要提交评测 → 本 Skill 只做"拉"，不做"评"
- 洛谷已登录 Cookie 的私密题目 → 见下文"鉴权"小节

---

## 工作流：先选路，再执行

```
Task Progress:
- [ ] Step 0: 判定走"路 A（直接执行）"还是"路 B（Subagent 并行）"
- [ ] Step 1: 解析用户输入，识别平台与题号列表
- [ ] Step 2: 准备输出目录
- [ ] Step 3: 执行（路 A：直接调脚本 / 路 B：下发 N 个并行子 Agent）
- [ ] Step 4: 验证输出文件（题数、样例齐全）
- [ ] Step 5: 汇总并告知用户
```

### Step 0: 选路（关键决策）

| 场景 | 走哪条路 |
|------|----------|
| 1 题、1 个平台 | **路 A**（直接执行，无需并行） |
| 同一平台 ≤50 题 / 1 场比赛 | **路 A**（脚本内部已并行） |
| **跨平台** / 多场比赛 / 多个 OJ 混合 | **路 B**（Subagent 并行） |
| 任务数 ≥3 且彼此独立 | **路 B**（Subagent 并行） |

**判定规则**（一票否决，任一命中则走路 B）：

1. 用户输入里出现 ≥2 个不同平台的题号 → 路 B
2. 用户输入里出现 ≥3 个独立任务单元 → 路 B
3. 用户明确说"并行 / 同时 / 一口气 / 一起 / 同时处理" → 路 B
4. 其他情况 → 路 A

---

## 路 A：直接执行（单平台 < 50 题）

按 5 步走：

### Step A1: 解析输入

用户输入通常长这样：

| 形式 | 示例 | 平台 |
|------|------|------|
| `P<number>` / `B<number>` / `U<number>` | `P1000`、`B2001`、`U123` | 洛谷 |
| `AT_<contest>_<task>` | `AT_abc001_a` | 洛谷/AtCoder |
| `<contestId><Letter>`（CF） | `1A`、`1800A`、`1800A2` | Codeforces |
| `HDU <number>` / `hdu<number>` | `HDU 1000`、`hdu1000` | HDUOJ |
| 牛客题号 | `NC16693`、`NC200001` | 牛客 |
| `<baseUrl> <id>` | `https://example.oj/problem?id=123` | 机构 OJ |

**大小写不敏感**：`p1000` = `P1000`。

**含糊输入必须先确认**（如"帮我拉洛谷第一题"），不要猜测。

### Step A2: 选择脚本

按 `scripts/fetch_<platform>.py` 选脚本。所有脚本通过 `scripts/common.py` 共享工具。

**平台识别优先级**（命中即停）：

1. `P`/`B`/`U` + 数字 → Luogu
2. `AT_` 前缀 → 先 Luogu，404 则回退 AtCoder
3. 数字+大写字母（`1800A`、`1A2`）→ Codeforces
4. `HDU`/`hdu` 前缀 → HDUOJ
5. `NC` 前缀数字 → Nowcoder
6. 给出 URL → `fetch_generic.py`
7. 仍无法识别 → 询问用户

完整 URL 模板和接口规范见 [platforms.md](platforms.md)。**子 Agent 的 prompt 必须包含这些判断规则**（详见"路 B"）。

### Step A3: 执行脚本

```bash
# 拉单题
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_luogu.py --problem P1000 --out ./problems/P1000.md

# 拉区间（脚本内置并发）
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_luogu.py --range P1000-P1010 --out ./problems/

# 拉 CF 整场（脚本内置 5 线程并发）
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_codeforces.py --contest 1800 --out ./problems/cf1800/

# 拉 AtCoder 整套
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_atcoder.py --contest abc001 --out ./problems/abc001/

# 通用抓取
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_generic.py --url https://oj.xxx.ac.cn/problem?id=123 --out ./problems/prob123.md
```

### Step A4: 验证输出

每个脚本打印：

```
✓ P1000 -> ./problems/P1000.md
  · Title: A+B Problem
  · Samples: 3 input/output pairs
```

某项 ✗ 时回退 [platforms.md](platforms.md) 或提示用户手工补齐。

### Step A5: 告知用户

回复要包含：
1. 输出文件**绝对路径列表**
2. **题数统计**（成功 / 失败）
3. **失败题目**清单 + 失败原因

---

## 路 B：Subagent 并行调度（多平台/多任务）

**触发条件**：见 Step 0 判定规则。

**核心思想**：每个子 Agent 负责一个独立任务单元（一个平台、一次比赛、一段区间），多个子 Agent **在同一次回复里同时下发**，由 Cursor IDE 并行执行。

### Step B1: 任务拆分

把用户输入拆成 N 个**互相独立**的"任务单元"。每个单元必须满足：

- **独立性**：不依赖其他单元的输出
- **可执行性**：能给出明确的脚本 + 参数
- **范围明确**：输出目录清晰无冲突

**拆分原则**：

| 用户输入 | 拆成几个单元 |
|----------|--------------|
| "拉 P1000 + 1800A + abc001_a + HDU 1000" | **4 个单元**（每平台一个） |
| "拉 CF round 1800 + ABC001 + 洛谷 P1000-P1010" | **3 个单元**（每场/区间一个） |
| "把所有牛客 NC 开头的前 100 题拉一下" | **1 个单元**（单平台大批量）→ 仍走路 A |
| "拉 P1000-P1100" | **1 个单元**（单平台大批量）→ 仍走路 A |

### Step B2: 为每个单元构造 Subagent Prompt

每个子 Agent 必须在 prompt 里看到**完整、可执行**的指令（不能假设子 Agent 也知道本 Skill）。**模板见 [subagent-prompts.md](subagent-prompts.md)**。

**Prompt 必须包含的字段**：

1. **任务**：明确"拉哪个平台、哪些题、输出到哪里"
2. **脚本调用**：完整的 `python ...` 命令（按 [platforms.md](platforms.md) 选脚本）
3. **Skill 引用**：开头说明"参考 `oi-problem-fetcher` Skill"，让子 Agent 也能读到这个 Skill
4. **输出契约**：最终必须输出"成功 N 题，失败列表 X"
5. **错误处理**：失败时**不要继续**，返回失败清单

### Step B3: 下发（一次回复里并行）

**关键**：必须在**同一次回复**里**同时发多个 Task 工具调用**，不要串行。

示例（伪代码）：

```
[同一回复内，同时发 4 个 Task 调用]
Task 1: subagent_type="generalPurpose", prompt="参考 oi-problem-fetcher Skill，调用 fetch_luogu.py --problem P1000 --out ./problems/luogu/P1000.md。请返回结果摘要。"
Task 2: subagent_type="generalPurpose", prompt="参考 oi-problem-fetcher Skill，调用 fetch_codeforces.py --problem 1800A --out ./problems/cf/1800A.md。请返回结果摘要。"
Task 3: subagent_type="generalPurpose", prompt="参考 oi-problem-fetcher Skill，调用 fetch_atcoder.py --task abc001_a --out ./problems/atcoder/abc001_a.md。请返回结果摘要。"
Task 4: subagent_type="generalPurpose", prompt="参考 oi-problem-fetcher Skill，调用 fetch_hduoj.py --problem 1000 --out ./problems/hduoj/HDU1000.md。请返回结果摘要。"
[4 个 Task 同时调用，Cursor IDE 并行执行]
```

`subagent_type` 通常用 `generalPurpose` 或 `shell`（脚本调用为主时优先 `shell`）。每个子 Agent 应该是**互不感知**的——它们之间不需要通信。

### Step B4: 汇总结果

等所有子 Agent 返回后，必须：

1. **聚合** N 个子 Agent 的输出
2. **检查文件**：用 `ls` 或 `glob` 兜底验证文件确实生成
3. **统计**：成功 N 题 / 失败 M 题
4. **失败项**：明确列出，方便用户决定是否重试

### Step B5: 回报用户

回复格式：

```
✓ 已完成 4 个并行任务
  · 洛谷 P1000    -> ./problems/luogu/P1000.md   (成功)
  · CF 1800A      -> ./problems/cf/1800A.md       (成功)
  · AtCoder abc001_a -> ./problems/atcoder/abc001_a.md (成功)
  · HDU 1000      -> ./problems/hduoj/HDU1000.md (成功)

总计：4/4 成功。
```

如果部分失败：

```
⚠️ 4 个任务中 3 成功，1 失败
  · 失败：CF 1800A - 子 Agent 报告 HTTP 403（疑似限流）
  · 建议：稍后重试，或换非高峰时段
```

---

## 并行 vs 串行的判断总结

| 场景 | 是否并行 | 怎么做 |
|------|----------|--------|
| 1 题 1 平台 | ❌ | 直接调脚本 |
| 1 平台 ≤50 题 | ❌ | 脚本内置并发（如 CF 5 线程） |
| 1 平台 >50 题 | ⚠️ | 拆成 5-10 个子 Agent，每个负责一段区间 |
| 跨平台 2-5 个 | ✅ | Subagent 并行 |
| 跨平台 6+ 个 | ✅ | Subagent 并行，但每批 ≤5 个并发避免风控 |
| 多场比赛 | ✅ | Subagent 并行，每场一个子 Agent |

**上限提醒**：并发子 Agent 数 **不宜超过 5**，否则容易触发平台风控。被风控后所有子 Agent 都会失败，必须串行等待。

---

## 输出格式

每个题目一个 `.md` 文件，统一模板见 [output-template.md](output-template.md)。要点：

- 文件名优先 `{题号}.md`（`P1000.md`）
- 多题必须分目录（如 `problems/luogu/`、`problems/cf/`）
- 必须包含：标题、原题描述、样例输入/输出
- 图片 / 公式：保留 HTML 标签，脚本日志里标"含 N 张图需手工补"

**多个子 Agent 的输出目录要预先对齐**（在 Step B1 拆分时定好），避免文件路径冲突。

## 鉴权

| 平台 | 是否需要登录 | 处理方式 |
|------|--------------|----------|
| 洛谷（公开题） | 否 | 直接抓 |
| 洛谷（私密/比赛题） | 是 | 需要 `LUOGU_COOKIE` 环境变量 |
| Codeforces | 否 | 公开 API |
| AtCoder | 否 | 公开 HTML |
| 牛客 | 部分题目需要登录 | 需要 `NOWCODER_COOKIE` 环境变量 |
| HDUOJ | 否 | 公开 |
| 机构 OJ | 看情况 | 通用抓取器允许传 `--cookie` |

**鉴权失败处理**：脚本不报错崩溃，回退到"只拿到部分内容"并在日志里标 ⚠️。

## 项目化使用（推荐）

建立 `problems-repo` 项目作为拉题工作区：

```
problems-repo/
├── problems/
│   ├── luogu/
│   ├── codeforces/
│   ├── atcoder/
│   ├── nowcoder/
│   └── hduoj/
├── contests/
└── .cursor/skills/ -> 指向 ~/.cursor/skills/oi-problem-fetcher
```

**首次初始化**：

```bash
mkdir -p problems-repo/problems problems-repo/contests
ln -s ~/.cursor/skills/oi-problem-fetcher problems-repo/.cursor/skills/oi-problem-fetcher
```

## 失败模式

| 现象 | 原因 | 解决 |
|------|------|------|
| HTTP 403 | 平台风控 / 缺 Cookie | 见"鉴权"小节 |
| HTML 解析出空题面 | 平台改版、选择器失效 | 去对应 references 看最新选择器 |
| 图片 / 公式丢失 | 部分 OJ 用 MathJax 渲染 | 提示用户手工核对 |
| 区间拉取中途失败 | 网络抖动 | 脚本 `--retry 3 --retry-delay 5` |
| 题目是付费/私密 | 平台限制 | 诚实告知，不绕过 |
| **并行时大量 HTTP 420/429** | 触发平台风控 | 降低并发数到 1-2，串行重试 |
| **子 Agent 报告"[非 JSON]"** | 子 Agent 用了不支持的工具 | 改 prompt 明确"用 shell 工具执行 Python" |

## 依赖安装

```bash
pip install requests beautifulsoup4 lxml html2text
```

## 自定义扩展

加新平台时：

1. 在 `scripts/` 下加 `fetch_<platform>.py`
2. 在 [platforms.md](platforms.md) 加平台速查行
3. 在 `references/` 加详细文档
4. 复用 `common.py` 的 `clean_html`、`write_problem_file` 即可

新增平台后，**别忘了同步更新 [subagent-prompts.md](subagent-prompts.md)**。

## 速查

| 用户说 | 走哪条路 | Agent 做 |
|--------|----------|----------|
| "帮我拉 P1000" | 路 A | `--problem P1000` |
| "拉洛谷 P1000-P1010" | 路 A | `--range P1000-P1010` |
| "CF round 1800 整场" | 路 A（脚本内置并发） | `--contest 1800` |
| "ABC001 所有题" | 路 A | `--contest abc001` |
| "同时拉 P1000、1800A、abc001_a、HDU 1000" | **路 B** | 4 个并行子 Agent |
| "把所有平台的入门题拉一下" | **路 B** | 按平台拆 4-6 个并行子 Agent |
| "把这个 OJ 的题拉一下 <URL>" | 路 A | `fetch_generic.py --url` |

## Additional Resources

- [platforms.md](platforms.md) — 各平台 URL/API/题号格式速查
- [output-template.md](output-template.md) — 输出 Markdown 模板
- [subagent-prompts.md](subagent-prompts.md) — **Subagent Prompt 模板**（路 B 必读）
- [examples.md](examples.md) — 完整使用示例
- [references/luogu.md](references/luogu.md) — 洛谷详细拉取说明
- [references/codeforces.md](references/codeforces.md) — CF 详细拉取说明
- [references/atcoder.md](references/atcoder.md) — AtCoder 详细拉取说明
- [references/nowcoder.md](references/nowcoder.md) — 牛客详细拉取说明
- [references/hduoj.md](references/hduoj.md) — HDUOJ 详细拉取说明
