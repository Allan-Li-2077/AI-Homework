# 使用示例

从用户的真实诉求出发，看编排 Agent 如何调度。

## 示例 1：单题（路 A）

**用户说**：「帮我把洛谷 P1000 拉下来」

**判定**：1 题 1 平台 → **路 A**

**编排 Agent 操作**：

```bash
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_luogu.py \
  --problem P1000 \
  --out ./problems/luogu/P1000.md
```

**回复**：

```
✓ P1000 -> ./problems/luogu/P1000.md
  · Title: A+B Problem
  · Samples: 3 input/output pairs
  · Tags: 入门, 数学
```

---

## 示例 2：单平台区间（路 A）

**用户说**：「拉洛谷 P1000-P1010」

**判定**：1 平台 11 题 → **路 A**（脚本内置串行即可）

**编排 Agent 操作**：

```bash
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_luogu.py \
  --range P1000-P1010 \
  --out ./problems/luogu/
```

**回复**：

```
✓ Done: 11 succeeded, 0 failed
  · P1000.md
  · P1001.md
  · ...
  · P1010.md
```

---

## 示例 3：单场比赛（路 A，但脚本内置并发）

**用户说**：「把 CF round 1800 整场拉下来」

**判定**：1 场比赛，CF 脚本自带 5 线程 → **路 A**

**编排 Agent 操作**：

```bash
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_codeforces.py \
  --contest 1800 \
  --out ./problems/cf1800/ \
  --workers 5
```

**回复**：

```
✓ Codeforces Round 1800: 7 problems fetched
  · 1800A.md (Two Buttons)
  · 1800B.md (Mere Array)
  · ...
  · README.md
```

---

## 示例 4：跨平台 4 题（路 B：4 个并行子 Agent）⭐

**用户说**：「同时拉 P1000、1800A、abc001_a、HDU 1000 这 4 题」

**判定**：跨平台 4 题 → **路 B**

**编排 Agent 操作**（**同一次回复内 4 个 Task 工具调用**）：

```
Task #1
  subagent_type: "shell"
  prompt: |
    【任务】拉取洛谷 P1000
    【执行】python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_luogu.py
            --problem P1000 --out ./problems/luogu/P1000.md
    【完成标准】文件存在且非空，否则返回失败原因
    【依赖】pip install requests beautifulsoup4 lxml

Task #2
  subagent_type: "shell"
  prompt: |
    【任务】拉取 CF 1800A
    【执行】python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_codeforces.py
            --problem 1800A --out ./problems/cf/1800A.md
    【完成标准】文件存在且非空

Task #3
  subagent_type: "shell"
  prompt: |
    【任务】拉取 AtCoder abc001_a
    【执行】python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_atcoder.py
            --task abc001_a --out ./problems/atcoder/abc001_a.md
    【完成标准】文件存在且非空

Task #4
  subagent_type: "shell"
  prompt: |
    【任务】拉取 HDUOJ 1000
    【执行】python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_hduoj.py
            --problem 1000 --out ./problems/hduoj/HDU1000.md
    【完成标准】文件存在且非空
```

**4 个子 Agent 并行执行**（IDE 在独立 thread 中跑），大约 5-10 秒完成。

**编排 Agent 汇总后回复**：

```
✓ 已完成 4 个并行任务（耗时 8.2s）
  · 洛谷 P1000       -> ./problems/luogu/P1000.md     (成功)
  · CF 1800A         -> ./problems/cf/1800A.md         (成功)
  · AtCoder abc001_a -> ./problems/atcoder/abc001_a.md (成功)
  · HDU 1000         -> ./problems/hduoj/HDU1000.md    (成功)

总计：4/4 成功
```

**对比**：如果串行调 4 个脚本，至少 4 × 1.5s = 6s；并行使 4 个网络请求同时跑，反而更快。

---

## 示例 5：多场比赛 + 区间（路 B：3 个并行子 Agent）

**用户说**：「把 CF round 1800、ABC001、洛谷 P1000-P1010 全部拉一下」

**判定**：3 个独立任务单元 → **路 B**

**任务拆分**：

| 单元 | 平台 | 范围 | 子 Agent |
|------|------|------|----------|
| 1 | Codeforces | contest 1800 整场 | 模板 2 |
| 2 | AtCoder | abc001 整场 | 模板 3 |
| 3 | Luogu | P1000-P1010 区间 | 模板 1 |

**编排 Agent 一次回复下发 3 个 Task**（每个指向不同子目录避免冲突）。

---

## 示例 6：大批量分区间并行（路 B，限制 5 并发）

**用户说**：「拉洛谷 P1000-P1100 共 101 题」

**判定**：1 平台 >50 题 → **路 B** 但要分批

**拆分策略**：

```
单元 1：P1000-P1020  → 子 Agent #1
单元 2：P1021-P1040  → 子 Agent #2
单元 3：P1041-P1060  → 子 Agent #3
单元 4：P1061-P1080  → 子 Agent #4
单元 5：P1081-P1100  → 子 Agent #5
```

**关键约束**：
- 5 个子 Agent **同时下发**（不是 5 串行）
- 每个子 Agent 输出到独立子目录：`./problems/luogu/p1/`, `./problems/luogu/p2/` 等
- 全部完成后归档到一个总目录

如果想更激进并发（10 个子 Agent），每个子 Agent 内区间更短（10 题），但 **总同时请求数仍是 10**，触发风控的概率升高。

---

## 示例 7：私密题（洛谷 Cookie）

**用户说**：「拉一下洛谷的比赛题 T123456」

**判定**：1 题 → 路 A，但需要 Cookie

**编排 Agent 操作**：

1. 提示用户提供 Cookie：`请在浏览器登录洛谷后复制 _uid 和 client_id Cookie 值`
2. 用户提供后：

```bash
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_luogu.py \
  --problem T123456 \
  --cookie "_uid=12345; client_id=xxxx" \
  --out ./problems/luogu/T123456.md
```

**或更安全**：

```bash
export LUOGU_COOKIE='_uid=12345; client_id=xxxx'
python ~/.cursor/skills/oi-problem-fetcher/scripts/fetch_luogu.py \
  --problem T123456 \
  --out ./problems/luogu/T123456.md
```

---

## 示例 8：混合成功+失败的汇总

**用户说**：「拉 P1000、1800Z（不存在）、abc001_a」

**编排 Agent 下发 3 个子 Agent**：

```
Task #1: 拉 P1000      → 成功
Task #2: 拉 1800Z      → 失败（CF 没这道题）
Task #3: 拉 abc001_a   → 成功
```

**汇总回复**：

```
✓ 已完成 3 个并行任务（耗时 5.1s）
  · P1000      -> ./problems/luogu/P1000.md     (成功)
  · 1800Z      -> 失败（CF 无此题，可能是 contest 1800 之后的新题）
  · abc001_a   -> ./problems/atcoder/abc001_a.md (成功)

总计：2/3 成功
```

**注意**：不能因为 1800Z 失败就放弃其他两个；必须分别处理每个子 Agent 的成功 / 失败状态。

---

## 示例 9：风控场景的应对

**用户说**：「拉到 50 道牛客、洛谷同步拉 50 道、CF 50 道」

**判定**：150 题跨平台 → **路 B**

**但**：牛客反爬严，**不能**同时 150+ 牛客请求。

**正确拆分**：

| 批次 | 任务 | 同时下发数 |
|------|------|------------|
| 1 | 洛谷 P1000-P1050 + AtCoder 题 + 牛客 NC16693-NC16742 | 3 个 |
| 2 | CF 整场 + 剩余 | 2 个 |

**或更安全的**：全程拆为 5 个子 Agent，每个只负责一个平台的一段。**不要**一行里发 10+ 个 Task。

---

## 编排 Agent 自检清单

回复用户前检查：

- [ ] **路选对了**？（单平台小批量 = 路 A；多平台 = 路 B）
- [ ] **子 Agent 全部返回**？（不能漏掉任何一个）
- [ ] **文件真的存在**？（用 ls 验证，不是听子 Agent 口头报告）
- [ ] **失败清单完整**？（不是只回报成功的）
- [ ] **输出目录无冲突**？（多子 Agent 同时写一个目录会互相覆盖）
- [ ] **回复简洁**？（用户只关心"成功 / 失败" + 文件路径）
