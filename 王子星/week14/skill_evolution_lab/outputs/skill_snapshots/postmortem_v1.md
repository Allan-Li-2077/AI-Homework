<!-- postmortem v1 | create on SKILL.md | 2026-08-06 20:38:40 -->
<!-- reason: 修复所有 10 条失败：值班助手对事后总结规则完全无知识，新建 Skill 入口指向参考文件。 -->


===== SKILL.md =====
---
name: postmortem
description: 事后总结（Postmortem）提交时限、是否强制，以及数据安全类事件的特殊总结要求。用于回答 P0/P1/P2/P3 事故事后总结多久提交、是否必须提交书面总结、审批人必须包含谁、需要包含什么评估结论等问题。
version: 1
---

# 事后总结（Postmortem）

回答事故解决后事后总结的提交时限、是否强制、数据安全类事件的特殊要求。

## 使用步骤

1. 先判断事故等级（P0/P1/P2/P3）
2. 根据等级查表得出提交时限与是否强制书面总结
3. 若涉及数据安全事件，额外套用特殊总结要求（必须含合规/法务评估结论，审批人必须包含法务代表）

详细规则见 [postmortem_rules.md](reference/postmortem_rules.md)。