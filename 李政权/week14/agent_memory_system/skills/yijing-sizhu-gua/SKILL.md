---
name: yijing-sizhu-gua
description: >-
  据姓名、性别、出生年月日与时辰，按四柱数字起本卦与变卦，动态生成八卦背景运势 HTML，
  并记录用时与 Token。Use when user says 算命、易经推命、排盘、本命卦、运势、生辰起卦，
  or provides 姓名+性别+生日+时辰 to request a fortune reading.
---

# 四柱起卦运势 Skill

## Goal
采集姓名、性别、出生年月日、时辰 → 推本卦/变卦 → **每次动态生成**八卦背景 HTML 运势页（非静态模板页），并落盘指标（用时、Token）。

## When to use
- 用户说「算命」「易经」「排盘」「本命卦」「看运势」
- 用户给出：`姓名 + 性别 + 生日 + 时辰`
- 显式：`/skill yijing-sizhu-gua` 或 `@yijing-sizhu-gua`

## Collect（缺一项则先问，勿猜）
1. 姓名
2. 性别（男/女；不便透露用「未注明」）
3. 出生日期：公历 `YYYY-MM-DD` 或 `YYYY年M月D日`
4. 时辰：子丑寅卯辰巳午未申酉戌亥（或钟点，由脚本映射）

示例输入：
`算命：李明，男，1990-08-15，辰时`

## Execute（必须跑脚本，不要手写 HTML）

```bash
python skills/yijing-sizhu-gua/scripts/generate_fortune.py "算命：李明，男，1990-08-15，辰时"
```

或：

```bash
python skills/yijing-sizhu-gua/scripts/generate_fortune.py \
  --name 李明 --gender 男 --birth 1990-08-15 --shichen 辰
```

成功时 stdout 最后一行为 JSON，含 `output_path`、`metrics`（elapsed_s / prompt_tokens / completion_tokens / total_tokens）。
默认输出：`outputs/fortune/{姓名}_{时间戳}.html`（**每次新建文件**）。
指标同步写入：`outputs/fortune/metrics_latest.json` 与 `metrics_log.jsonl`。

## Response rules
- 告知 HTML 路径（及 Web 下 `/fortune/{文件名}`）
- 用 4～8 条要点概括：本卦、变卦、命局底色、近中远期走势
- **不要**在聊天里粘贴整段 HTML
- 顺带告知本次 Skill 用时与 Token（来自执行结果）
- 语气沉稳、鼓励；禁止恐吓与绝对吉凶承诺
- 声明：传统文化咨询，非科学预测，不替代医疗/法律/投资决策

## Rules
- 总解读控制在约 2000 字内（写入 HTML 正文）
- HTML 由脚本字符串动态拼装，八卦图样为内联 SVG 背景，无外网 CDN
- 禁止使用预置静态结果页；每次运行重新起卦、重新生成文件
