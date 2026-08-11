---
name: preference-interview
description: >-
  Conducts a short structured interview to fill USER.md profile fields
  (name, location, job, preferences). Use when the user says 完善画像,
  采访我, 了解我一下, fill my profile, or wants to update personal preferences
  systematically.
---

# Preference Interview

## Goal
通过短问答补全用户画像，便于后续 Memory Flush 写入 USER.md。

## Workflow
1. 一次只问 **1~2** 个问题，不要一次性抛出问卷
2. 优先覆盖空缺字段：姓名 → 职业 → 所在地 → 偏好 → 沟通习惯
3. 用户答完后，用一两句话复述确认，再问下一项
4. 用户说「先这样 / 够了」时立即停止，并给出已收集摘要

## Question bank（按需选用）
- 怎么称呼你？
- 目前主要做什么工作/学习？
- 常驻城市或时区？
- 有没有饮食、工具、工作时段方面的偏好？
- 希望我回答时更简洁还是更详细？

## Rules
- 语气自然，像朋友聊天，不要像表单机器人
- 已从 USER.md 知道的信息不要重复追问，可轻量确认
- 结束时列出「本次新了解到的信息」清单，方便用户 `/flush`

## Additional resources
- 追问技巧见 [reference.md](reference.md)
