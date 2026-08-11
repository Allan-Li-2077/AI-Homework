# ARCHITECTURE.md — AI Agent 框架对比 Subagent 并行调研系统

## 1. 项目定位

**场景**：用户在多个 AI Agent 开发框架之间做技术选型（如 LangGraph vs AutoGen vs CrewAI vs Dify），主 agent 自主派发多个 subagent 并行调研各候选框架，聚合为对比矩阵 + 按场景推荐。

**核心设计**：
- 主 agent 是 ReAct 循环，**有 2 个工具**：`web_search`（单次搜索）和 `dispatch_subagents`（派发多个 subagent 并行调研各框架）。
- subagent 也是 ReAct 循环（只有 `web_search`），ThreadPoolExecutor 并行执行。
- 可视化：左侧拓扑图 + 右侧点节点看 ReAct 过程，紫色科技主题。

**范式归属**：动态 Orchestrator-Workers——主 agent 按候选框架数决定派几个 subagent。

**与 market_research 的差异**：
| | market_research | agent_framework_comparison |
|---|---|---|
| 拆解逻辑 | 按调研侧面 | 按候选框架 |
| subagent 任务 | 搜销量/竞争/政策 | 搜 LangGraph/AutoGen/CrewAI 等 |
| 报告形态 | 结构化分析报告 | 对比矩阵 + 分场景推荐 |
| 主题色 | cyan | violet/purple |

## 2. 整体流水线

```
用户问题（如 "LangGraph vs AutoGen vs CrewAI vs Dify"）
   ↓
主 agent ReAct 循环（工具: web_search + dispatch_subagents）
   ├─ 单一框架 → 直接 web_search → Final Answer
   └─ 多框架对比 → dispatch_subagents("LangGraph调研|AutoGen调研|...")
                       ↓
              ┌─ subagent1 ReAct(LangGraph) ──┐
              ├─ subagent2 ReAct(AutoGen)  ───┤ 并行(ThreadPool)
              ├─ subagent3 ReAct(CrewAI)  ────┤
              └─ subagent4 ReAct(Dify)    ────┘
                       ↓ 汇总（各框架五维评价）
              主 agent 综合成对比矩阵 → Final Answer
```

## 3. 评价维度

每个 subagent 按五维评价其负责的框架：
1. 核心架构（设计理念、编排模式、状态管理）
2. 上手难度（文档质量、学习曲线、示例丰富度）
3. 工具生态与集成（LLM支持、工具链、第三方集成）
4. 社区活跃度（GitHub stars、贡献者数、更新频率）
5. 适用场景（简单链式/多Agent协作/生产部署/低代码/学术）

主 agent 综合为对比矩阵 + 按场景推荐。

## 4. 目录结构

```
agent_framework_comparison/
├── src/
│   ├── llm_client.py
│   ├── tavily_search.py
│   ├── react_loop.py
│   ├── agents.py            # MAIN_SYSTEM: AI框架对比 prompt
│   ├── serve.py             # port 8004
│   └── eval_compare.py     # 4 题 A/B
├── static/
│   ├── index.html           # 紫色AI科技主题
│   └── viz/topology.js
├── outputs/
├── requirements.txt
├── ARCHITECTURE.md
├── USAGE_GUIDE.md
└── RESUME_GUIDE.md
```
