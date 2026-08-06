---
name: incident-triage
description: 判断故障等级（P0-P3）及对应响应时限。用于一线值班收到告警后需要定级的场景。
version: 1
---

# 故障分级（Incident Triage）

一线值班收到告警后，先判断故障等级，再决定响应时限。

## 使用步骤

1. 判断影响范围（核心服务 / 非核心服务 / 单用户边缘case）
2. 判断已持续时长
3. 对照分级标准得出 P0-P3
4. 查表得出对应响应时限

详细的分级标准表格见 [severity_levels.md](reference/severity_levels.md)。

<!-- v1: 初始版本 -->
