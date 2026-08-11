# 铁力健身俱乐部会员客服 Agent 自进化实验

> 基于 Skill 驱动的 LLM 客服系统，通过 Nudge 机制实现 Skill 自动进化，并对比臃肿版与优化版 Skill 在 token 消耗与准确率上的差异。

---

## 目录

- [1. 项目背景与目标](#1-项目背景与目标)
- [2. 实用工具说明](#2-实用工具说明)
- [3. 项目结构](#3-项目结构)
- [4. 环境配置](#4-环境配置)
- [5. 完整实验流程](#5-完整实验流程)
- [6. 各方案原理简介](#6-各方案原理简介)
- [7. 实验执行过程与日志](#7-实验执行过程与日志)
- [8. 评估结果汇总](#8-评估结果汇总)
- [9. 结果分析与讨论](#9-结果分析与讨论)
- [10. 最终结论](#10-最终结论)
- [11. 产出文件索引](#11-产出文件索引)
- [12. 常见问题](#12-常见问题)
- [附录 A：企业级落地方案](#附录-a企业级落地方案)
- [附录 B：技术细节](#附录-b技术细节)

---

## 1. 项目背景与目标

### 1.1 背景

传统 LLM 客服系统存在两大痛点：

| 痛点 | 表现 | 后果 |
|------|------|------|
| **幻觉** | LLM 凭"通用知识"编造退货期限、退款比例等具体数字 | 客户投诉、法律风险 |
| **不可进化** | 政策变更后需人工重写 Prompt / 微调模型 | 维护成本高、响应慢 |

本项目采用 **Skill 驱动 + Nudge 自进化** 方案解决这两个问题：
- Skill 是结构化的可执行 SOP（非 RAG 式政策搬运），Agent 只需"照做"
- Nudge 机制在检测到失败样本后自动触发 Reviewer 分析并修改 Skill

### 1.2 场景选择：健身房会员客服

选择"铁力健身俱乐部"作为实验场景，理由：

1. **人人都懂** —— 会员卡、私教课、冻结、转让、团课等概念无需解释
2. **规则分层丰富** —— 年卡/季卡/月卡/体验卡 × 6 大政策领域，交叉点多
3. **可虚构具体数字** —— LLM 不可能"猜到"冻结 2 个月、转让手续费 15% 等具体规则
4. **基线低、进化空间大** —— 初始只有 2 个 Skill，基线准确率约 22%

### 1.3 实验目标

| 实验 | 目标 | 指标 |
|------|------|------|
| **实验一：自进化实验** | 验证 Nudge 机制能否自动补全缺失 Skill | 准确率提升幅度 |
| **实验二：Skill 效率对比** | 对比臃肿版 vs 优化版 Skill 的 token 消耗与准确率 | token 节省率、准确率差异 |

---

## 2. 实用工具说明

### 2.1 三种运行方式

| 方式 | 脚本 | 用途 | 适合场景 |
|------|------|------|---------|
| **A. Web UI** | `serve.py` | 可视化演示自进化全过程 | 课堂演示、汇报 |
| **B. 命令行全流程** | `src/demo_runner.py` | 80 题逐块运行 + 自动 Nudge | 完整实验 |
| **C. 独立规则评估** | `src/rule_eval_with_review.py` | 用当前 Skill 跑 60 题快速评估 | 验证 Skill 效果 |
| **D. Skill 效率对比** | `src/skill_efficiency_compare.py` | 记录每题 token 消耗并对比 | 效率优化分析 |

### 2.2 工具对照表

```
用户提问 → Agent.answer() → DeepSeek API → 回答
                ↑                                      ↓
         SkillManager.load_all()              Evaluator.evaluate_answer()
                ↑                                      ↓
         skills/*/SKILL.md              required关键词命中？→ ✓/✗
```

---

## 3. 项目结构

```
self_evolving_agent/
├── data/                          # 数据层
│   ├── policies.md                # 健身房会员政策手册（Ground Truth 来源）
│   ├── eval_set.json              # 60 题评估集（6 类 × 关键词判定）
│   └── demo_script.json           # 80 题演示脚本（8 块 × 10 题 + Nudge 触发点）
│
├── src/                           # 代码层
│   ├── agent.py                   # 客服 Agent：用 Skill 回答问题
│   ├── skill_manager.py           # Skill 管理器：创建/修改/版本追踪
│   ├── background_reviewer.py     # Reviewer：分析失败样本 → 输出改 Skill 方案
│   ├── evaluator.py               # 评估器：关键词匹配判定对错
│   ├── demo_runner.py             # 实验主程序：80 题逐块运行 + Nudge
│   ├── rule_eval_with_review.py   # 独立评估：60 题快速跑
│   └── skill_efficiency_compare.py # 效率对比：记录 token 消耗
│
├── skills/                        # Skill 文件（活动版）
│   ├── basic_membership/SKILL.md  # 基础会员权益（v2）
│   ├── personal_training/SKILL.md # 私教课规则（v2）
│   ├── freeze_policy/SKILL.md     # 请假冻结（v1，Nudge 自动创建）
│   ├── transfer_policy/SKILL.md   # 转让规则（v1，Nudge 自动创建）
│   ├── group_class/SKILL.md       # 团课预约（v1，Nudge 自动创建）
│   └── membership_refund/SKILL.md # 入会退会（v2，Nudge 自动创建+修补）
│
├── skills_optimized_backup/       # 优化版 Skill 备份（自进化产物）
│
├── outputs/                       # 输出层
│   ├── evolution_log.json         # 自进化实验完整日志
│   ├── efficiency_compare_bloated.json    # 臃肿版 token 消耗详情
│   ├── efficiency_compare_optimized.json  # 优化版 token 消耗详情
│   ├── rule_eval_full.json        # 60 题逐题评估详情
│   ├── skill_versions/            # Skill 版本历史（JSON）
│   ├── skill_snapshots/           # 每版 Skill 的 .md 快照
│   └── eval_runs/                 # 每次评估的逐题结果
│
├── serve.py                       # FastAPI Web 服务
├── index.html                     # 前端可视化界面
├── requirements.txt               # 依赖：openai>=1.0.0
├── ARCHITECTURE.md                # 架构设计文档
├── USAGE_GUIDE.md                 # 使用指南
├── RESUME_GUIDE.md                # 简历文案
└── README.md                      # 本文件
```

---

## 4. 环境配置

### 4.1 依赖安装

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境（Windows PowerShell）
.\.venv\Scripts\Activate.ps1

# 安装依赖
pip install openai>=1.0.0
```

### 4.2 API Key 配置

API Key **不写入代码**，在终端运行时通过环境变量传入：

```powershell
$env:DEEPSEEK_API_KEY="sk-你的key"
```

### 4.3 系统要求

| 项目 | 要求 |
|------|------|
| Python | ≥ 3.10 |
| 操作系统 | Windows / macOS / Linux |
| API | DeepSeek API（兼容 OpenAI SDK） |
| 网络 | 需能访问 `api.deepseek.com` |

---

## 5. 完整实验流程

### 5.1 实验一：自进化实验

```powershell
# 1. 设置 API Key
$env:DEEPSEEK_API_KEY="sk-你的key"

# 2. 运行自进化实验（约 6-8 分钟）
.\.venv\Scripts\python.exe -u src\demo_runner.py
```

实验流程：
```
基线评估 60 题 → 记录初始准确率
    ↓
Block 1-8（每块 10 题）：
  跑 10 题 → 有失败？
    是 → 失败样本注入 Reviewer → 输出 create/patch JSON → SkillManager 执行 → Probe Eval 30 题
    否 → 跳过 Nudge（零成本）
    ↓
最终评估 60 题 → 记录进化后准确率
    ↓
evolution_log.json 落盘
```

### 5.2 实验二：Skill 效率对比

```powershell
# 步骤 1：用臃肿版 Skill 跑评估
.\.venv\Scripts\python.exe -u src\skill_efficiency_compare.py --label bloated

# 步骤 2：换回优化版 Skill
Remove-Item -Recurse -Force skills\*
Copy-Item -Recurse -Force skills_optimized_backup\* skills\

# 步骤 3：用优化版 Skill 跑评估
.\.venv\Scripts\python.exe -u src\skill_efficiency_compare.py --label optimized
# 脚本会自动检测两版结果并输出对比报告
```

### 5.3 方式 A：Web UI 演示

```powershell
$env:DEEPSEEK_API_KEY="sk-你的key"
.\.venv\Scripts\python.exe -m uvicorn serve:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000
```

### 5.4 方式 C：独立规则评估

```powershell
$env:DEEPSEEK_API_KEY="sk-你的key"
.\.venv\Scripts\python.exe -u src\rule_eval_with_review.py
```

---

## 6. 各方案原理简介

### 6.1 Skill ≠ RAG

```
❌ RAG 式（政策搬运，Agent 还要"推理"→ 容易幻觉）
  退款政策：普通会员30天可退，VIP60天，限时特惠不可退...

✅ Skill 式（结构化 SOP，Agent 只需"照做"→ 更可靠）
  ## 退货期限
  - 普通会员：签收后30天内可退
  - VIP会员：60天内可退
  - 限时特惠：不可退
```

### 6.2 Nudge 自进化机制

```
         每 N 题（nudge_interval=10）
                    ↓
           全对？──是──→ 跳过（零成本，不调 LLM）
                    ↓ 否
      失败样本（仅失败题，非全量）→ Reviewer
                    ↓
        Reviewer 输出 JSON：create 或 patch
                    ↓
      SkillManager 执行修改 + 存版本快照
                    ↓
        Probe Eval 30 题固定集 → 记录当前准确率
```

**关键设计**：Reviewer 只接收失败样本（不传全量对话），避免"美学式补全"。

### 6.3 三种 Skill 进化操作

| 操作 | 触发条件 | 示例 |
|------|---------|------|
| **patch（补分支）** | Skill 已存在但缺少某条规则 | basic_membership v1→v2：补"体验卡不享任何附加权益" |
| **create（建新 Skill）** | 发现完全未覆盖的领域 | freeze_policy v1：从无到有创建冻结规则 |
| **patch（重写提示强度）** | 同样信息但 LLM 忽略 | membership_refund v1→v2：加"可以"关键词 |

### 6.4 评估器原理

```python
# 契约式评估：三步判定
def evaluate(answer, question):
    # 1. 推脱检测：回答含"联系人工"→ 一票否决（即使碰巧含关键词也判错）
    if "联系人工" in answer: return False, "推脱"

    # 2. 必须关键词：ground_truth.required 中所有词都必须出现
    for kw in required:
        if kw not in normalize(answer): return False, f"缺少关键词: {kw}"

    # 3. 禁止关键词：ground_truth.forbidden 中所有词都不能出现
    for kw in forbidden:
        if kw in normalize(answer): return False, f"禁止词出现: {kw}"

    return True, "通过"
```

### 6.5 Skill 效率对比原理

```
同一套 60 题，同一套评估器，同一套 system prompt 模板
                    ↓
     ┌────────────────────────────────────┐
     │     臃肿版 Skill（1 文件/4560 字符）  │ → 跑 60 题 → 记录 token
     │     优化版 Skill（6 文件/2318 字符）  │ → 跑 60 题 → 记录 token
     └────────────────────────────────────┘
                    ↓
            对比：准确率 / input tokens / output tokens / 总 tokens
```

---

## 7. 实验执行过程与日志

### 7.1 实验一：自进化实验日志

#### 基线评估（初始 2 个 Skill）

```
Skills: basic_membership (v1), personal_training (v1)
总体准确率: 13/60 = 21.7%

分类准确率:
  basic_membership    8/10  80%   ← 初始 Skill 覆盖良好
  personal_training   5/12  42%   ← 部分覆盖（只有预约/有效期）
  freeze_rule         0/12   0%   ← 完全缺失
  transfer_rule       0/12   0%   ← 完全缺失
  group_class         0/ 8   0%   ← 完全缺失
  join_refund         0/ 6   0%   ← 完全缺失
```

#### Block 1 (basic_membership, seq 1-10)：8/10 = 80%

```
失败 2 条：Q01（年卡回答缺"可以"）、Q10（体验卡权益未明确否定）
→ Nudge 触发：Reviewer 分析 → patch basic_membership
  补充："体验卡：不享任何附加权益（无体测、无免费饮水）"
→ Probe Eval: 6/30 = 20.0%
```

#### Block 2 (freeze_rule, seq 11-20)：0/10 = 0%

```
失败 10 条：冻结规则全部缺失，Agent 全部推脱
→ Nudge 触发：Reviewer 分析 → create freeze_policy
  新建 Skill 覆盖：常规冻结、特殊冻结、冻结期间规则
→ Probe Eval: 11/30 = 36.7%
```

#### Block 3 (personal_training, seq 21-30)：6/10 = 60%

```
失败 4 条：旷课后果、过期处理、转让、退费、签字确认缺失
→ Nudge 触发：Reviewer 分析 → patch personal_training
  补充：旷课扣1次、20%激活费、不可转让、退费70%、需签字
→ Probe Eval: 14/30 = 46.7%
```

#### Block 4 (transfer_rule, seq 31-40)：8/10 = 80%

```
失败 2 条：私教课不可随卡转让、转让后有效期不变
→ Nudge 触发：Reviewer 分析 → create transfer_policy
  新建 Skill 覆盖：转让条件、流程、限制
→ Probe Eval: 19/30 = 63.3%
```

#### Block 5 (group_class, seq 41-50)：8/10 = 80%

```
失败 2 条：爽约禁约规则、体验卡不可预约团课
→ Nudge 触发：Reviewer 分析 → create group_class
  新建 Skill 覆盖：预约、取消、爽约、签到、装备、体验卡限制
→ Probe Eval: 23/30 = 76.7%
```

#### Block 6 (join_refund, seq 51-60)：0/10 = 0%

```
失败 10 条：入会退会规则全部缺失
→ Nudge 触发：Reviewer 分析 → create membership_refund
  新建 Skill 覆盖：冷静期、常规退会、特殊退会
→ Probe Eval: 28/30 = 93.3%
```

#### Block 7 (freeze_pt_cross, seq 61-70)：10/10 = 100%

```
全对！冻结×私教交叉规则已被 freeze_policy 中的"冻结期间私教课继续计时"覆盖
→ 跳过 Nudge 和 Probe Eval（零成本）
```

#### Block 8 (mixed_validation, seq 71-80)：9/10 = 90%

```
失败 1 条：Q80 特殊疾病退费回答缺"可以"关键词
→ Nudge 触发：Reviewer 分析 → patch membership_refund
  修改："特殊疾病...可以全额退还未使用部分"（强调"可以"）
→ Probe Eval: 29/30 = 96.7%
```

#### 最终评估

```
总体准确率: 59/60 = 98.3%
分类准确率:
  basic_membership    9/10   90%
  personal_training  12/12  100%
  freeze_rule        12/12  100%
  transfer_rule      12/12  100%
  group_class         8/ 8  100%
  join_refund         6/ 6  100%
```

#### 进化轨迹汇总

| 时间点 | 准确率 | 新增/修改的 Skill | 操作类型 |
|--------|--------|-------------------|---------|
| 基线 | 13/60 = 21.7% | — | — |
| Nudge #1 (seq=10) | 6/30 = 20.0% | basic_membership v1→v2 | patch |
| Nudge #2 (seq=20) | 11/30 = 36.7% | freeze_policy v1（新建） | create |
| Nudge #3 (seq=30) | 14/30 = 46.7% | personal_training v1→v2 | patch |
| Nudge #4 (seq=40) | 19/30 = 63.3% | transfer_policy v1（新建） | create |
| Nudge #5 (seq=50) | 23/30 = 76.7% | group_class v1（新建） | create |
| Nudge #6 (seq=60) | 28/30 = 93.3% | membership_refund v1（新建） | create |
| Block 7 (seq=70) | 跳过 | — | 全对跳过 |
| Nudge #8 (seq=80) | 29/30 = 96.7% | membership_refund v1→v2 | patch |
| **最终** | **59/60 = 98.3%** | **共 7 个 Skill 操作** | — |

### 7.2 实验二：Skill 效率对比日志

#### 臃肿版 Skill 设计

```
文件数: 1 (bloated_all_in_one/SKILL.md)
字符数: 4,560
特点:
  - 所有 6 个领域的规则塞进 1 个大文件
  - 散文式描述："年卡的价格是1888元，有效期是365天，也就是整整一年的时间..."
  - 同一信息重复表述
  - 无结构化列表，无优先级标识
  - 大量解释性文字和客套话
```

#### 优化版 Skill 设计

```
文件数: 6（按领域分模块）
字符数: 2,318（总和）
特点:
  - 每个领域独立 Skill 文件（200-400 字/个）
  - 结构化列表："- 年卡：不限次入场，有效期365天"
  - 优先级标识："冻结期间私教课继续计时，不暂停（此规则优先于一切冻结特权）"
  - 无冗余，每条规则只说一次
  - 交叉陷阱用 ⚠️ 标识
```

#### 对比结果（自动输出）

```
指标                     臃肿版        优化版        差异
------------------------------------------------------------
准确率                   91.7%       98.3%       +6.7%
总 input tokens       157,327      82,567     -74,760
总 output tokens        1,266       1,000        -266
总 tokens             158,593      83,567     -75,026
平均每题 input            2,622       1,376      -1,246
平均每题 output              21          17          -4
平均每题 total            2,643       1,393      -1,250
System prompt 字符数    4,560       2,318      -2,242
Skill 文件数               1           6          +5
```

---

## 8. 评估结果汇总

### 8.1 自进化实验结果

| 指标 | 数值 |
|------|------|
| 基线准确率 | 21.7% (13/60) |
| 进化后准确率 | 98.3% (59/60) |
| 准确率提升 | +76.6% |
| Nudge 触发次数 | 7 次（Block 7 全对跳过） |
| Skill 操作总数 | 7 个（4 个 create + 3 个 patch） |
| 最终 Skill 文件数 | 6 个 |

### 8.2 Skill 效率对比结果

| 指标 | 臃肿版 | 优化版 | 变化 |
|------|--------|--------|------|
| 准确率 | 91.7% | 98.3% | +6.7% |
| 总 input tokens | 157,327 | 82,567 | **-47.5%** |
| 总 output tokens | 1,266 | 1,000 | -21.0% |
| 总 tokens | 158,593 | 83,567 | **-47.3%** |
| 平均每题 input | 2,622 | 1,376 | -47.5% |
| 平均每题 output | 21 | 17 | -21.0% |
| 平均每题 total | 2,643 | 1,393 | -47.3% |
| System prompt 字符数 | 4,560 | 2,318 | -49.2% |
| Skill 文件数 | 1 | 6 | +5 |

### 8.3 分类准确率对比

| 类别 | 基线 | 臃肿版 | 优化版 | 最终 |
|------|------|--------|--------|------|
| basic_membership | 80% | 90% | 90% | 90% |
| personal_training | 42% | 100% | 100% | 100% |
| freeze_rule | 0% | 92% | 100% | 100% |
| transfer_rule | 0% | 83% | 100% | 100% |
| group_class | 0% | 88% | 100% | 100% |
| join_refund | 0% | 100% | 100% | 100% |

### 8.4 分类 token 消耗对比

| 类别 | 臃肿版 input | 优化版 input | 节省 |
|------|-------------|-------------|------|
| basic_membership (10题) | 26,223 | 13,763 | -47.5% |
| personal_training (12题) | 31,478 | 16,526 | -47.5% |
| freeze_rule (12题) | 31,457 | 16,505 | -47.5% |
| transfer_rule (12题) | 31,453 | 16,501 | -47.5% |
| group_class (8题) | 20,976 | 11,008 | -47.5% |
| join_refund (6题) | 15,740 | 8,264 | -47.5% |

> **注**：每题 input token 节省率几乎一致（~47.5%），因为 input token 主要取决于 system prompt 长度（Skill 内容），与问题内容无关。

---

## 9. 结果分析与讨论

### 9.1 自进化实验分析

#### 为什么基线只有 21.7%？

初始只有 2 个 Skill：
- `basic_membership` 覆盖了基础会员卡类型和入场规则 → 8/10 能答对
- `personal_training` 只覆盖了私教课的预约和有效期 → 5/12 能答对
- 其他 4 个领域完全无覆盖 → Agent 按"契约"诚实回答"需要联系人工客服" → 0%

这验证了**契约式设计**的价值：不覆盖就诚实推脱，而非幻觉编造。

#### 为什么 Block 7 能全对跳过？

Block 7 是"冻结×私教课交叉"题。在 Block 2 创建 `freeze_policy` 时，Reviewer 就在 Skill 中写入了"冻结期间私教课继续计时，不暂停（此规则优先于一切冻结特权）"。这个前瞻性的规则覆盖了后续交叉题，说明 **Reviewer 能从失败样本中提取出通用规则，而非仅修当前题**。

#### Nudge 机制的成本效率

| Nudge | 调用 LLM 次数 | 结果 |
|-------|-------------|------|
| Block 7 全对跳过 | 0 次 | 零成本 |
| Block 8 仅 1 题失败 | Reviewer 1 次 + Probe 30 次 | 最小成本 |
| Block 2 全部失败 | Reviewer 1 次 + Probe 30 次 | 一次 create 解决 10 题 |

关键设计：**Probe Eval 使用固定 30 题子集**（而非 60 题全量），在保证信号的同时节省 50% 评估成本。

### 9.2 Skill 效率对比分析

#### 为什么优化版 token 消耗少 47%？

```
臃肿版 System Prompt（4,560 字符）:
  "年卡的价格是1888元，有效期是365天，也就是整整一年的时间。
   年卡最大的特点和优势在于不限次入场，这意味着年卡会员可以在
   一年内随时来健身房锻炼，没有入场次数的限制，想来多少次就来多少次..."

优化版 System Prompt（2,318 字符）:
  "- 年卡：不限次入场，有效期365天"
```

同样信息，优化版用 1 行结构化列表替代了臃肿版 3-4 行散文。6 个领域累计节省 2,242 字符 → input token 从 2,622 降到 1,376。

#### 为什么优化版准确率反而更高？

| 失败类别 | 臃肿版丢分原因 | 优化版为何不丢 |
|---------|--------------|-------------|
| transfer_rule (83% vs 100%) | 散文中"私教课不可随卡转让"被淹没在大段文字中，LLM 未能定位 | 独立 Skill 文件中单独一行"- 私教课不可随卡转让"，LLM 直接命中 |
| group_class (88% vs 100%) | 爽约规则"3次禁约1周"被团课装备描述干扰 | 独立小节"## 取消规则"中清晰列出 |
| freeze_rule (92% vs 100%) | "冻结期间私教课继续计时"规则在散文中不够突出 | 末尾标注"此规则优先于一切冻结特权"，LLM 注意到优先级 |

**结论**：结构化 Skill 不仅省 token，还因信息定位更清晰而提升准确率。

#### 为什么 output token 也有差异（21 vs 17）？

臃肿版的散文式描述"感染"了 LLM 的回答风格，使其回答也更冗长。优化版的简洁列表让 LLM 回答也更直接。

### 9.3 交叉陷阱验证

设计了 5 个交叉陷阱，全部在进化后正确处理：

| 陷阱 | 描述 | 验证题 | 结果 |
|------|------|--------|------|
| A | 冻结期间私教课继续计时（不暂停） | Q33 | ✓ |
| B | 私教课不可随卡转让 | Q45 | ✓ |
| C | 体验卡不享任何附加特权 | Q10, Q34, Q38, Q54 | ✓ |
| D | 已开卡不支持冷静期退款 | Q56 | ✓ |
| E | 已冻结的卡不可转让 | Q46 | ✓ |

---

## 10. 最终结论

### 10.1 实验一结论

> **Nudge 自进化机制有效**：从 21.7% 到 98.3%，7 次 Skill 操作（4 create + 3 patch），无需人工干预。Reviewer 能从失败样本中提取通用规则，前瞻性覆盖后续交叉题。

### 10.2 实验二结论

> **结构化 Skill 在 token 消耗和准确率上均优于散文式 Skill**：
> - Token 消耗降低 **47.3%**（158,593 → 83,567）
> - 准确率提升 **6.7%**（91.7% → 98.3%）
> - System prompt 字符数减少 **49.2%**（4,560 → 2,318）
>
> 核心原因：结构化列表让 LLM 更快定位关键规则，减少"在散文中搜索"的注意力消耗。

### 10.3 综合结论

| 维度 | 散文式 Skill | 结构化 Skill（自进化产物） |
|------|-------------|----------------------|
| 准确率 | 91.7% | **98.3%** |
| Token 效率 | 2,643 tokens/题 | **1,393 tokens/题** |
| 可维护性 | 难（一个大文件） | **易（6 个独立模块）** |
| 可进化性 | 难（改一处影响全局） | **易（patch 精确定位）** |

**最佳实践**：Skill 应按领域分模块、用结构化列表、标注优先级、每条规则只说一次。

---

## 11. 产出文件索引

### 数据文件

| 文件 | 说明 |
|------|------|
| [policies.md](data/policies.md) | 健身房会员政策手册（6 章 + 5 个交叉陷阱） |
| [eval_set.json](data/eval_set.json) | 60 题评估集（6 类 × required/forbidden 关键词） |
| [demo_script.json](data/demo_script.json) | 80 题演示脚本（8 块 × 10 题 + Nudge 触发点） |

### 代码文件

| 文件 | 说明 |
|------|------|
| [agent.py](src/agent.py) | 客服 Agent：用 Skill 回答问题 |
| [skill_manager.py](src/skill_manager.py) | Skill 管理器：create/patch/版本追踪 |
| [background_reviewer.py](src/background_reviewer.py) | Reviewer：失败样本分析 → Skill 修改方案 |
| [evaluator.py](src/evaluator.py) | 评估器：关键词匹配 + 推脱检测 |
| [demo_runner.py](src/demo_runner.py) | 实验主程序：80 题逐块 + Nudge |
| [rule_eval_with_review.py](src/rule_eval_with_review.py) | 独立评估：60 题快速跑 |
| [skill_efficiency_compare.py](src/skill_efficiency_compare.py) | 效率对比：token 消耗记录 |
| [serve.py](serve.py) | FastAPI Web 服务 |

### Skill 文件（进化后最终版）

| 文件 | 版本 | 创建方式 |
|------|------|---------|
| [basic_membership/SKILL.md](skills/basic_membership/SKILL.md) | v2 | 初始 + patch |
| [personal_training/SKILL.md](skills/personal_training/SKILL.md) | v2 | 初始 + patch |
| [freeze_policy/SKILL.md](skills/freeze_policy/SKILL.md) | v1 | Nudge create |
| [transfer_policy/SKILL.md](skills/transfer_policy/SKILL.md) | v1 | Nudge create |
| [group_class/SKILL.md](skills/group_class/SKILL.md) | v1 | Nudge create |
| [membership_refund/SKILL.md](skills/membership_refund/SKILL.md) | v2 | Nudge create + patch |

### 输出文件

| 文件 | 说明 |
|------|------|
| [evolution_log.json](outputs/evolution_log.json) | 自进化完整日志（Skill 版本 + 评估记录 + Nudge 事件） |
| [efficiency_compare_bloated.json](outputs/efficiency_compare_bloated.json) | 臃肿版逐题 token 消耗 |
| [efficiency_compare_optimized.json](outputs/efficiency_compare_optimized.json) | 优化版逐题 token 消耗 |
| [rule_eval_full.json](outputs/rule_eval_full.json) | 60 题逐题评估详情 |
| [skill_snapshots/](outputs/skill_snapshots/) | 每版 Skill 的 .md 快照 |
| [eval_runs/](outputs/eval_runs/) | 每次评估的逐题结果 |

---

## 12. 常见问题

### Q1: 为什么不用 RAG？

RAG 把政策原文丢给 LLM，LLM 还要"推理"出具体规则 → 容易幻觉。Skill 是结构化 SOP，Agent 只需"照做"，更可靠。且 Skill 可以被 Nudge 精确 patch，而 RAG 的向量检索无法被"修改"。

### Q2: 为什么基线准确率只有 21.7%？

初始只有 2 个 Skill（basic_membership + personal_training），覆盖 2/6 个领域。其他 4 个领域的题，Agent 按"契约"诚实回答"需要联系人工客服"，判为 0 分。这是设计意图：**宁可诚实推脱，不可幻觉编造**。

### Q3: Nudge 机制和微调有什么区别？

| 维度 | Nudge | 微调 |
|------|-------|------|
| 修改对象 | Skill 文件（外挂知识） | 模型权重 |
| 成本 | 1 次 LLM 调用（Reviewer） | 大量 GPU 训练 |
| 可解释性 | 高（Skill 是人类可读的 .md） | 低（权重黑盒） |
| 可回滚 | 是（版本快照） | 否 |
| 响应速度 | 秒级 | 小时/天级 |

### Q4: 为什么臃肿版准确率也有 91.7%？

臃肿版虽然散文式，但**信息是完整的**（所有 60 题的答案都在其中）。丢分的 5 题是因为冗余文字干扰了 LLM 对关键规则的定位，而非信息缺失。这说明"信息在"不等于"LLM 能找到"。

### Q5: 为什么每题 input token 节省率都是 47.5%？

Input token = system prompt（固定）+ 用户问题（很短）。由于 system prompt 占 input 的 99%+，而两版 system prompt 的字符数差异是固定的（4560 vs 2318），所以每题的节省率几乎一致。

### Q6: 可以用 GPT-4 / Claude 替代 DeepSeek 吗？

可以。只需修改 `agent.py` 中的 `base_url` 和 `model` 参数。OpenAI SDK 兼容所有支持 Chat Completions API 的模型。

### Q7: 如何添加新的政策领域？

1. 在 `policies.md` 中添加新章节
2. 在 `eval_set.json` 中添加新类别的题目
3. 在 `demo_script.json` 中添加对应的 block
4. 运行 `demo_runner.py`，Nudge 机制会自动创建新 Skill

---

## 附录 A：企业级落地方案

### A.1 从实验到生产的改造路线

| 维度 | 实验版 | 生产版 |
|------|--------|--------|
| Skill 存储 | 本地 .md 文件 | 数据库 / 对象存储 |
| 版本管理 | 文件系统快照 | Git / 数据库版本表 |
| 评估集 | 60 题静态 JSON | 持续收集线上日志 → 自动标注 |
| Nudge 触发 | 每 10 题固定 | 基于失败率滑动窗口动态触发 |
| Reviewer | 单次 LLM 调用 | 多轮迭代 + 人工审核 |
| 部署 | 单机脚本 | 微服务 + 消息队列 |

### A.2 线上集成架构

```
用户消息 → API Gateway → Agent Service → 回答用户
                            ↓
                     失败检测（用户反馈/兜底率）
                            ↓
                     Nudge Queue（异步）
                            ↓
                     Reviewer Service → 修改 Skill
                            ↓
                     审核流（人工 Review）→ 发布
```

### A.3 成本估算

以 DeepSeek API 为例（每百万 token 约 ¥1-2）：

| 场景 | 每题 token | 每月题量 | 月成本 |
|------|-----------|---------|--------|
| 臃肿版 | 2,643 | 100,000 | ¥265-530 |
| 优化版 | 1,393 | 100,000 | ¥139-278 |

**优化版每月节省约 47%**，且准确率更高。

### A.4 监控指标

| 指标 | 告警阈值 | 处理方式 |
|------|---------|---------|
| 准确率 | < 90% | 触发 Nudge |
| 推脱率 | > 20% | 检查 Skill 覆盖范围 |
| 平均回答延迟 | > 3s | 检查 Skill 长度 |
| Nudge 频率 | > 3次/天 | 人工介入审查 |

---

## 附录 B：技术细节

### B.1 Agent 系统提示词

```python
SYSTEM_TEMPLATE = """你是铁力健身俱乐部的会员客服助手。

你的所有知识来源于以下技能文档，严格基于文档内容回答，不要自行推断或编造政策。

## 回答规则（严格遵守）
- 【能回答】如果技能文档覆盖了用户问题：直接给出完整具体的答案。
  不要在答案中加"建议联系人工客服"之类的推脱话。
- 【不能回答】如果技能文档确实不覆盖：仅回答一句 "需要联系人工客服"。

{skills_section}
"""
```

### B.2 评估器数字归一化

```python
def _normalize(text: str) -> str:
    """全角→半角数字，用于关键词匹配"""
    return text.replace("０","0").replace("１","1")...replace("９","9")
```

### B.3 SkillManager patch 机制

```python
def patch_skill(skill_name, patches):
    """
    patches: [{"old": "旧文本", "new": "新文本"}, ...]
    精确文本替换，不重写整个文件
    """
    content = read_skill(skill_name)
    for p in patches:
        content = content.replace(p["old"], p["new"])
    write_skill(skill_name, content)
    save_snapshot(skill_name, version+1)
```

### B.4 Reviewer 输出格式

```json
{
  "action": "create",          // 或 "patch"
  "skill_name": "freeze_policy",
  "content": "## 常规冻结\n- 年卡：每年可冻结2个月...",
  "patches": [],               // patch 模式时使用
  "reason": "修复所有冻结规则相关推脱问题（10条）"
}
```

### B.5 演示脚本设计原理

```
Block 1: basic_membership     → 预期全对或接近（初始 Skill 覆盖）
Block 2: freeze_rule          → 预期全错（完全缺失）→ 触发 create
Block 3: personal_training    → 预期部分失败 → 触发 patch
Block 4: transfer_rule        → 预期全错 → 触发 create
Block 5: group_class          → 预期全错 → 触发 create
Block 6: join_refund          → 预期全错 → 触发 create
Block 7: freeze_pt_cross      → 预期全对（Block 2 已前瞻覆盖）→ 跳过
Block 8: mixed_validation     → 预期接近全对 → 小幅 patch
```

每块纯类别设计确保失败信号清晰：如果某块失败，Reviewer 能立即定位到缺失的领域，不会被混合类别的噪音干扰。

### B.6 效率对比脚本核心逻辑

```python
for qid in sorted(ev.questions.keys()):
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},  # 固定（含 Skill）
            {"role": "user", "content": question},          # 变化（每题不同）
        ],
        temperature=0,    # 确保可复现
        max_tokens=400,
    )
    # 从 response.usage 提取 token 消耗
    prompt_tokens = response.usage.prompt_tokens      # = system + question
    completion_tokens = response.usage.completion_tokens  # = answer
```

---

*文档生成时间：2026-08-05*
*实验环境：Python 3.10 + DeepSeek API + Windows 11*
