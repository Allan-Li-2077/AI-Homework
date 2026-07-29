---
name: demo-data-process
version: 1.0
description: 处理数据列表并生成统计报告
trigger: 当需要生成数据统计时触发
dependencies: []
parameters:
  - name: data
    type: list
    required: true
    description: 数据列表（数字）
  - name: operation
    type: str
    required: false
    default: summary
    description: 操作类型（summary/filtering/sorting）
returns:
  type: dict
  description: 处理结果字典
---

# 数据处理

## 功能说明

对输入的数据列表进行多种处理操作，包括：
- summary: 生成数据统计摘要（平均值、最大值、最小值等）
- filtering: 过滤出大于中位数的数据
- sorting: 返回排序后的数据

## 示例

```
输入：data=[1, 2, 3, 4, 5], operation="summary"
输出：{
  "count": 5,
  "sum": 15,
  "avg": 3.0,
  "min": 1,
  "max": 5,
  "median": 3
}

输入：data=[1, 2, 3, 4, 5], operation="filtering"
输出：{"filtered": [4, 5], "count": 2}
```

## 参数详解

- **data** (必需，list): 数字列表
- **operation** (可选，str): 处理操作
  - summary: 生成统计摘要（默认）
  - filtering: 过滤数据
  - sorting: 排序数据

## 执行流程

1. 验证数据列表非空
2. 根据 operation 选择处理逻辑
3. 进行数据计算
4. 返回处理结果

## 教学意义

- 演示复杂参数处理（list）
- 展示多个操作分支
- 体现结果作为字典返回（便于链式执行）
