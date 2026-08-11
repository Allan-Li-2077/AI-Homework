---
name: weekly-review
description: >-
  Summarizes recent memories and daily logs into a structured weekly review.
  Use when the user asks for 周报, 周回顾, weekly review, 本周总结, or to review
  what happened this week based on MEMORY.md and daily logs.
---

# Weekly Review

## When to use
用户想回顾本周进展、写周报、或梳理近期记忆时启用。

## Workflow
1. 优先引用 System Prompt 中的「近期日志」与「长期记忆」条目
2. 若有语义检索结果，纳入相关事实
3. 按下列模板输出，缺信息处写「暂无记录」而不是编造

## Output template

```markdown
# 本周回顾

## 要点
- …

## 决策与约定
- …

## 偏好/事实更新
- …

## 下周可跟进
- …
```

## Rules
- 只使用已注入的记忆内容，不臆造事件
- 引用记忆时自然融入，不要罗列「来源：MEMORY.md」
- 保持简洁，总长控制在一屏内
