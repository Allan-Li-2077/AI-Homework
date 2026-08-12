# Subagent Prompt 模板（路 B 必读）

路 B 调度的子 Agent **不自动知道本 Skill**，必须把所有执行细节写进 prompt。

## 通用 prompt 头部（所有子 Agent 都要带）

```
你是一个 OI 题目拉取子 Agent。请按以下指令执行，不要发挥：
1. 阅读并遵循 ~/.cursor/skills/oi-problem-fetcher/SKILL.md 的"路 A"工作流
2. 调用对应的 fetch_*.py 脚本（路径在 ~/.cursor/skills/oi-problem-fetcher/scripts/）
3. 完成后必须用文件写入工具或 ls 工具**实际验证**文件已生成
4. 失败时立刻停止，把失败原因原样返回
5. 完成后输出**这份摘要**：
   - 成功 N 题，输出文件路径列表
   - 失败 M 题（题号 + 错误信息）
   - 脚本运行总耗时
```

下面 6 个模板直接复制替换 `{}` 占位符即可。

## 模板 1：洛谷单题 / 区间

```
【任务】拉取洛谷题目

【前置】阅读 ~/.cursor/skills/oi-problem-fetcher/SKILL.md（路 A：直接执行）

【执行】
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_luogu.py \
  {--problem P1000 | --range P1000-P1010} \
  --out {./problems/luogu/}

【依赖】pip install requests beautifulsoup4 lxml

【完成标准】
- 目标目录有 {N} 个 .md 文件
- 每个文件非空、含题面 + 样例
- 失败题号列表（如有）

【不要做】
- 不要拉私密题，除非提供 LUOGU_COOKIE
- 不要生成 README
- 不要修改其他平台的脚本
```

## 模板 2：Codeforces 整场 / 单题

```
【任务】拉取 Codeforces 题目

【前置】阅读 ~/.cursor/skills/oi-problem-fetcher/SKILL.md（路 A）

【执行】
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_codeforces.py \
  {--contest 1800 | --problem 1800A | --range 1800A-1800E --contest 1800} \
  --out {./problems/cf/} \
  --workers 5

【依赖】pip install requests beautifulsoup4 lxml

【完成标准】
- 目标目录有 {N} 个 .md 文件 + 1 个 README.md
- 每个文件含 rating（如果题有）
- 失败题号列表

【注意】CF 限流 1 req/s，--workers 5 已是上限
```

## 模板 3：AtCoder 整场 / 单题

```
【任务】拉取 AtCoder 题目

【前置】阅读 ~/.cursor/skills/oi-problem-fetcher/SKILL.md（路 A）

【执行】
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_atcoder.py \
  {--contest abc001 | --task abc001_a} \
  --out {./problems/atcoder/}

【依赖】pip install requests beautifulsoup4 lxml

【完成标准】
- 目标目录有 {N} 个 .md 文件
- 比赛模式额外有 README.md
- 失败题号列表

【注意】样例按编号 O(1) 索引配对；如发现输出空，先确认比赛已结束
```

## 模板 4：HDUOJ 单题 / 区间

```
【任务】拉取 HDUOJ 题目

【前置】阅读 ~/.cursor/skills/oi-problem-fetcher/SKILL.md（路 A）

【执行】
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_hduoj.py \
  {--problem 1000 | --range 1000-1010} \
  --out {./problems/hduoj/}

【依赖】pip install requests beautifulsoup4 lxml

【完成标准】
- 目标目录有 {N} 个 .md 文件
- 失败题号列表

【注意】HDU 是 GBK 编码，脚本已处理；老题可能没有样例展示
```

## 模板 5：牛客网单题

```
【任务】拉取牛客题目

【前置】阅读 ~/.cursor/skills/oi-problem-fetcher/SKILL.md（路 A）

【执行】
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_nowcoder.py \
  {--problem NC16693 | --url https://www.nowcoder.com/practice/xxx} \
  --out {./problems/nowcoder/}

【依赖】pip install requests beautifulsoup4 lxml

【完成标准】
- 目标目录有 {N} 个 .md 文件
- 失败题号列表

【注意】牛客页面结构不稳定，可能解析出空题面 → 列入失败清单
```

## 模板 6：机构 OJ（通用抓取）

```
【任务】拉取机构 OJ 题目

【前置】阅读 ~/.cursor/skills/oi-problem-fetcher/SKILL.md（路 A）

【执行】
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_generic.py \
  --url {https://oj.xxx.ac.cn/problem?id=123} \
  --out {./problems/inst/}

【依赖】pip install requests beautifulsoup4 lxml

【完成标准】
- 目标目录有 {N} 个 .md 文件
- 失败题号列表

【注意】通用抓取结构可能不准确，标注为"通用 OJ"输出
```

## 多任务"一次性下发"示例

用户说："同时拉 P1000、1800A、abc001_a、HDU 1000 这 4 题"

**编排 Agent 应当这样下发**（同一次回复里 4 个 Task 调用）：

```
Task #1（洛谷）
  subagent_type: "shell"
  prompt: 模板 1，--problem P1000 --out ./problems/luogu/

Task #2（CF）
  subagent_type: "shell"
  prompt: 模板 2，--problem 1800A --out ./problems/cf/ --workers 5

Task #3（AtCoder）
  subagent_type: "shell"
  prompt: 模板 3，--task abc001_a --out ./problems/atcoder/

Task #4（HDU）
  subagent_type: "shell"
  prompt: 模板 4，--problem 1000 --out ./problems/hduoj/
```

每个子 Agent 完成后**只回报摘要**，编排 Agent 汇总后统一回复用户。

## 子 Agent 类型选择

| subagent_type | 适用场景 |
|---------------|----------|
| `shell` | **优先选**：拉题=执行 Python 脚本，shell 子 Agent 适合 |
| `generalPurpose` | 需要解释/判断（如"这道题是否适合初中生"）时备用 |
| `explore` | 不适合本任务（探索型，非执行型） |

## 反模式（不要做）

| 反模式 | 后果 |
|--------|------|
| 让子 Agent "推断" 平台 | 误识别率 > 30% |
| 子 Agent 内再次下达子 Agent | 嵌套 subagent，Cursor 不支持 |
| Prompt 不写明输出目录 | 子 Agent 写到默认目录，结果文件找不到 |
| Prompt 不写"失败立刻停止" | 子 Agent 继续爬无关内容浪费时间 |
| 7+ 个并发子 Agent | 触发所有平台风控，全部失败 |
| 子 Agent 用 `explore` type | 拿到的是"读文件"而不是"执行命令" |
