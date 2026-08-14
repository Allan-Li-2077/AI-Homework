---
name: research_workflow
version: 1.0.0
description: 研究型多步任务：先用 web_search 收集信息，再 summarize 提炼要点，最后 code_review 验证（如有代码）
keywords: [研究, research, 调研, 综合, 多步骤, deep dive]
triggers: [research_request, deep_analysis]
execution: workflow
parameters:
  - name: topic
    type: string
    required: true
    description: 研究主题
  - name: depth
    type: string
    required: false
    description: 研究深度：quick（只搜+总结）/ standard（搜+总结+交叉验证）/ deep（再加追问）
---

# Research Workflow Skill（execution=workflow）

这是一个**多步工作流** skill，按 YAML 顺序串行调用其他 skill。

## 步骤流程（标准版，depth=standard）
1. **web_search**：联网收集 `{{topic}}` 的最新信息
2. **summarize**：把收集到的信息提炼为结构化要点
3. （可选）若涉及代码或方案比较，**code_review** 验证技术细节

## 步骤流程（quick 版）
1. **web_search**
2. **summarize**

## 输入参数
- 主题：`{{topic}}`
- 深度：`{{depth | default:standard}}`

具体步骤定义见 `workflow.yaml`。