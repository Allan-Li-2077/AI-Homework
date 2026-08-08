---
name: memory-cite
description: >-
  Answers questions by explicitly citing loaded long-term memories and
  retrieval hits. Use when the user asks 你还记得, 根据记忆, cite memory,
  引用记忆, or wants transparent sources for what the agent recalls.
disable-model-invocation: false
---

# Memory Cite

## Goal
回答依赖记忆的问题时，让引用可见、可核对。

## Workflow
1. 先扫描：语义检索结果 → MEMORY 近期条目 → 每日日志 → USER.md
2. 有命中：先给直接答案，再附「依据」小节
3. 无命中：明确说「当前记忆里没有」，再请用户补充；禁止编造

## Answer format

```markdown
（直接回答）

**依据**
- [类别] 标题或原句摘要
- …
```

## Rules
- 「依据」最多 3 条，选最相关的
- 用户纠正记忆时，以当轮表述为准，并提示可用 `/flush` 固化
- 不要假装检索了未注入的内容
