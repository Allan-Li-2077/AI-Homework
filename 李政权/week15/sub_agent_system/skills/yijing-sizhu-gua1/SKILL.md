---
name: yijing-sizhu-gua1
description: >-
  Clone of yijing-sizhu-gua: cast hexagrams from name/gender/birth/shichen, then
  let the LLM generate the full fortune HTML (bagua-styled page). Use when user
  says yijing-sizhu-gua1, @yijing-sizhu-gua1, /skill yijing-sizhu-gua1, or
  「LLM生成运势页」「用大模型生成算命HTML」。
---

# 四柱起卦运势 Skill（LLM 生成 HTML 版）

## Goal
与 `yijing-sizhu-gua` 相同的起卦流程；差异是：**完整 HTML 页面由 LLM 生成**（非 Python 模板拼装正文/样式），每次动态落盘，并记录用时与 Token。

## When to use
- 显式：`/skill yijing-sizhu-gua1` 或 `@yijing-sizhu-gua1`
- 用户说「用 LLM 生成算命 HTML」「LLM 运势页」
- 需要对比「模板 HTML」与「模型生成 HTML」时

## Collect（缺一项则先问）
姓名、性别、公历生日、时辰。  
例：`@yijing-sizhu-gua1 算命：李明，男，1990-08-15，辰时`

## Execute（必须跑脚本）

```bash
python skills/yijing-sizhu-gua1/scripts/generate_fortune_llm_html.py \
  "@yijing-sizhu-gua1 算命：李明，男，1990-08-15，辰时"
```

输出：`outputs/fortune1/{姓名}_{时间戳}.html`  
指标：`outputs/fortune1/metrics_latest.json` / `metrics_log.jsonl`

## Response rules
- 告知路径（Web：`/fortune1/{文件名}`）、本卦/变卦、用时与 Token
- **不要**在聊天里粘贴整段 HTML
- 语气沉稳；声明为文化咨询，非科学预测

## Rules
- HTML 必须由 LLM 产出完整文档（含 `<!DOCTYPE html>`）；脚本只负责起卦、调模型、校验与落盘
- 要求页面简洁、八卦图样背景、无外网 CDN
- 失败时可回落本地模板 HTML，并在 metrics 中标注 `fallback`
