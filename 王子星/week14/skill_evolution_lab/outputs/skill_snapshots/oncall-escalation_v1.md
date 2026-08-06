<!-- oncall-escalation v1 | initial on SKILL.md | 2026-08-06 20:22:29 -->
<!-- reason: 初始版本 -->


===== SKILL.md =====
---
name: oncall-escalation
description: 值班升级链路，判断告警何时应从一线升级到二线/三线。
version: 1
---

# 值班升级（On-call Escalation）

判断告警在什么条件下需要从一线升级到二线，以及二线何时需要升级到三线。

## 使用步骤

1. 判断当前处于升级链路的哪一环（一线/二线/三线）
2. 查看具体升级触发条件和对应时限
3. 给出是否应该升级、升级到哪一层

详细的升级链路和时限见 [escalation_chain.md](reference/escalation_chain.md)。

<!-- v1: 初始版本 -->


===== reference/escalation_chain.md =====
# 升级链路

## 基础升级链路
- 一线（Primary On-call）收到告警后需在5分钟内确认（Acknowledge）
- 一线确认后若在15分钟内未能给出处置方向，自动升级至二线（Secondary On-call）
- 二线介入后，若在30分钟内判断需要更高层级支持，需升级至三线（Engineering Manager）
- 三线以上需要总监级介入的情况：仅限P0且预计恢复时间（ETA）超过2小时

<!-- v1: 初始版本 -->
