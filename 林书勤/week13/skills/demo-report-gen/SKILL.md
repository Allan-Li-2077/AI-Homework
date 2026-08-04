---
name: demo-report-gen
version: 1.0
description: 生成综合报告（依赖前置数据）
trigger: 当需要生成最终报告时触发
dependencies: [demo-data-process]
parameters:
  - name: title
    type: str
    required: false
    default: 数据分析报告
    description: 报告标题
  - name: demo_data_process
    type: dict
    required: false
    description: 前置 skill 的处理结果（会自动注入）
returns:
  type: dict
  description: 完整的报告对象
---

# 报告生成

## 功能说明

基于前置 skill (demo-data-process) 的处理结果，生成一份格式化的综合报告。

演示**依赖注入**机制：
- demo-data-process 的结果作为 demo_data_process 参数自动注入
- 无需显式传递，harness 自动管理依赖

## 示例

```
执行链：demo-data-process → demo-report-gen
输入：data=[1,2,3,4,5], operation="summary"

Step 1: demo-data-process 处理数据
  输出: {count: 5, sum: 15, avg: 3.0, ...}

Step 2: demo-report-gen 接收到 demo-data-process 的结果
  自动注入为 demo_data_process 参数
  输出：{
    title: "数据分析报告",
    generated_at: "2024-01-01T12:00:00",
    source_operation: "summary",
    statistics: {...},
    sections: [...]
  }
```

## 参数详解

- **title** (可选，str): 报告标题
- **demo_data_process** (可选，dict): 前置结果（自动注入，不需要手动传）

## 执行流程

1. 接收 demo-data-process 的处理结果
2. 构建报告标题和元数据
3. 组织报告各部分（摘要、分析、建议）
4. 返回完整报告对象

## 教学意义

- 演示 skill 间的依赖关系
- 展示自动依赖注入机制
- 体现链式执行的便利性
- 说明参数命名规则（skill-name → skill_name）
