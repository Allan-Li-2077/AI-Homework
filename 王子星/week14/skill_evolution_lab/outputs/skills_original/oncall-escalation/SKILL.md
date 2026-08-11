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
