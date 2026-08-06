<!-- public-communication v1 | create on SKILL.md | 2026-08-06 20:37:16 -->
<!-- reason: 修复全部 10 条失败：缺少对外公告类 Skill，导致值班助手推脱『需要人工判定』 -->


===== SKILL.md =====
---
name: public-communication
description: 对外沟通与公告规则，包括客户可见故障的公告时限（P0/P1）和公告更新频率。用于回答何时必须发公告、公告时限多久、更新频率等问题。
version: 1
---

# 对外沟通与公告（Public Communication）

处理故障期间对外公告的发布时机、时限和更新频率。

## 使用步骤

1. 判断故障是否客户可感知（如页面报错、服务中断）还是内部故障（客户不可感知）
2. 根据故障等级（P0/P1）对照公告时限规则，确定发布对外公告的时限
3. 若已发布公告，根据故障等级确定公告更新频率

详细规则见 [announcement_rules.md](reference/announcement_rules.md)。
