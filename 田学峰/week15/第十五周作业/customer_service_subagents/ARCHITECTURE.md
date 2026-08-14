# ARCHITECTURE.md — 智能客服 Subagent 并行调度系统

## 1. 项目定位

**场景**：客户提一个客服问题，主客服 agent 自主决定是否派发多个专长子客服并行处理不同子任务，聚合成礼貌分点的客服答复。落地「subagent 并行」范式，凸显并行加速优势。

**核心设计**（对应需求）：
- 主客服 agent 是 ReAct 循环，**2 个工具**：`direct_handle`（直接处理简单问题）和 `dispatch_subagents`（派发多专长子客服并行处理）。主 agent **根据问题自主决定**用哪个——LLM 自主路由，非固定拓扑。
- 子客服也是 ReAct 循环（带对应专长工具集），多个子客服用 `ThreadPoolExecutor` 并行执行 → 并行优势。
- 可视化：**左侧拓扑图**（主节点 + 派发时动态加入的子客服节点），**右侧点节点看 ReAct 过程**，可不断切换。

**范式归属**：动态 Orchestrator-Workers（主客服决定派几个、派什么专长，拓扑运行时生长）。

## 2. 整体流水线

```
客户问题
   ↓
主客服 agent ReAct 循环（工具: direct_handle + dispatch_subagents）
   ├─ 单一极简 → direct_handle → Final Answer
   └─ 多子任务 → dispatch_subagents("任务1#order | 任务2#after_sale | 任务3#faq")
                    ↓
           ┌─ 子客服1 ReAct(order 工具) ──┐
           ├─ 子客服2 ReAct(after_sale) ──┤ 并行(ThreadPool)
           └─ 子客服3 ReAct(faq) ─────────┘
                    ↓ 汇总（含并行加速统计）
           主客服综合成礼貌分点答复 → Final Answer
```

脚本对应：`customer_tools.py`(客服工具) → `react_loop.py`(通用 ReAct) → `agents.py`(主客服+派发) → `serve.py`(SSE) → `eval_compare.py`(A/B)。

## 3. 各环节技术选型

### 3.1 客服工具集（customer_tools.py，mock 数据）
5 个 mock 工具覆盖客服核心场景：
- `query_order`：订单详情（5 个 mock 订单 A100001~A100005）
- `query_logistics`：物流轨迹（3 个 mock 单号）
- `apply_refund`：发起退款（生成 RFD- 工单号，校验状态）
- `query_faq`：政策查询（退货/发票/会员/保修/配送 6 条 mock 知识）
- `escalate_human`：升级人工（生成 ES- 工单号）

按专长打包为 `SUBAGENT_TOOLSETS`：`order` / `after_sale` / `faq` / `escalation`，每个 subagent 实例化时取对应专长工具集。零外部依赖，纯标准库 mock。

### 3.2 通用 ReAct 引擎（react_loop.py）
主客服和子客服共用同一个 `ReActLoop` 类，区别只在 `tools` 字典：
- 主客服：`{direct_handle, dispatch_subagents}`
- 子客服：`{order 工具集}` / `{after_sale 工具集}` / ...

经典 ReAct：LLM 输出 `Thought/Action/Action Input`，用 `stop=["Observation:"]` 在 Action Input 后截断，runner 执行工具得 Observation 续写。**完整 trace 捕获**（每步 Thought/Action/ActionInput/Observation）供可视化。

解析兜底：LLM 拿到长结果后常直接写答复不带 `Final Answer:` 前缀，`_parse` 检测到无 Action 但有实质文本时当作 Final Answer。`role_desc` 参数把专长描述（如"订单专员"）写进 prompt 增强专业性。

### 3.3 主客服自主决策（agents.py）
系统提示 `MAIN_SYSTEM` 给明确决策原则 + worked example：
- 2 个及以上子任务（查/退/咨询/升级）→ **必须** `dispatch_subagents`
- 单一极简问题 → `direct_handle`

`dispatch_subagents` 输入是 `任务1#专长1 | 任务2#专长2`（管道分隔任务，#后是专长类型 order/after_sale/faq/escalation），主 agent 自主拆分并标注专长。派发后 N 个子客服并行，主客服收齐汇总 Observation 综合成答复。

### 3.4 并行执行（凸显优势的核心）
`ThreadPoolExecutor(max_workers=N)` 并行跑 N 个子客服 ReAct。量化：`wall_clock`（并行墙钟）vs `serial_sum`（各子客服时长之和 = 串行基线）。`serial=True` 模式退化为 for 循环（eval A/B 真实对比基线）。

### 3.5 可视化（static/index.html + viz/topology.js）
- **可视化代码隔离**：SVG 拓扑动画在 `viz/topology.js`（vanilla JS 无依赖），主流程 UI 在 index.html。
- **深色科技主题**：渐变背景、玻璃卡片(backdrop-blur)、霓虹标题(渐变文字)、发光节点(SVG filter glow)、运行节点脉冲(半径周期变化)、流光虚线边、monospace observation。
- 左侧拓扑：主节点先画，`dispatch` 事件到达时动态加子客服节点 + 主→子边，节点按 `subagent_step` 实时脉冲、`done` 变绿。
- 右侧过程流：**默认"全部实时流"**——所有节点(main + 各子客服)每步按到达顺序实时滚动，带节点 badge。点左侧节点按钮 → 只看该节点；点"全部实时流"回到全部。
- 切换问题：`TopoViz` 构造时整体换图，不堆叠。

## 4. 实验结果（预期）

### 4.1 端到端客服
典型多任务问题（查物流 + 退款 + 政策）：主客服 2 步（`dispatch_subagents` → `Final Answer`），派发 3 个子客服（订单专员查物流 + 售后专员处理退款 + 政策专员回答政策），各子客服 ReAct 1~3 步。答复分点组织带工单号。

### 4.2 Parallel vs Serial A/B
| 问题 | 并行墙钟 | 串行墙钟 | dispatch 加速 |
|------|---------|---------|--------------|
| 多任务客服 1 | ~10s | ~25s | 2.5× |
| 多任务客服 2 | ~12s | ~30s | 2.5× |

**结果解读**：
- dispatch 加速 2~3×：多个独立子任务并行，墙钟从 sum 压到 ≈max。
- 总墙钟加速小于 dispatch 加速：主客服自身串行开销（规划 + 综合的 LLM 调用）不并行化，拉低总加速比（Amdahl 定律）。
- 子客服数由主客服自主决定，非硬编码。

### 4.3 与 Orchestrator-Workers 对应
- 拓扑：动态 Orchestrator-Workers（主客服派发，节点运行时生长）
- 用图理由：多异构节点协作 ✓、可并行分支 ✓、需独立验证 ✓
- 并行 vs 顺序：serial 基线是顺序对照，量化并行收益

## 5. 优化方向

| 层面 | 方向 |
|------|------|
| 并行收益 | 主客服规划/综合也异步化，或用更便宜快模型做规划降串行段占比 |
| 子客服 | 失败重试、子任务结果去重、工单持久化 |
| 决策 | 主客服决策不稳定时加规则兜底（问题含多个动作关键词强制 dispatch）|
| 可视化 | 拓扑加边动画（dispatch 时主→子流光）、trace 自动滚动跟随 |
| 工程 | 子客服数上限保护、会话上下文记忆、工单库持久化 |
| 真实落地 | mock 工具替换为真实订单/物流/退款 API 接口 |

## 6. 关键工程决策

| 问题 | 根因 | 解法 |
|------|------|------|
| 主客服不派发、自己串行处理多任务 | `MAIN_SYSTEM` 没传给 ReActLoop | ReActLoop 加 `system_prompt` 参数，主客服传 `MAIN_SYSTEM` |
| prompt 光说"必须 dispatch"无效 | ReAct 需 worked example 教格式 | MAIN_SYSTEM 加 `dispatch_subagents` 完整示例（含 #专长 标注）|
| 拿到长结果后输出空 action 撞 max_steps | LLM 直接写答复不带 `Final Answer:` 前缀 | `_parse` 兜底：无 Action 有文本 → 当 Final Answer |
| dispatch observation 过长撑爆 context | 多子客服全文回灌 | 每子结果截短到 500 字喂回主客服（完整 trace 仍在 shared_state 供 viz）|
| SSE 跨线程 | run 在线程跑，StreamingResponse 在主线程 | queue 桥接：回调 push 队列，SSE 主循环 get+yield |
| 子客服专长混乱 | 单一工具集所有子客服共用 | `SUBAGENT_TOOLSETS` 按专长打包，`get_toolset(role)` 取对应集 |

## 7. 目录结构

```
customer_service_subagents/
├── src/
│   ├── llm_client.py        # 极简 DeepSeek 客户端
│   ├── customer_tools.py     # 客服工具集（mock：订单/退款/物流/FAQ/升级）
│   ├── react_loop.py         # 通用 ReAct 引擎（主/子客服共用）
│   ├── agents.py             # 主客服 + dispatch_subagents 并行派发
│   ├── serve.py              # FastAPI + SSE 流式
│   └── eval_compare.py       # parallel vs serial A/B
├── static/
│   ├── index.html            # 左拓扑右trace切换 主流程 UI
│   └── viz/topology.js       # SVG 拓扑动画（隔离，非教学重点）
├── outputs/
│   └── eval_compare.json
├── requirements.txt
├── ARCHITECTURE.md
└── USAGE_GUIDE.md
```
