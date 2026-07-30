# ARCHITECTURE.md — 单一主流程的 ReAct Financial Agent

## 1. 目标

当前实现只保留一条 agent 主链路：

用户问题 → LLM 规划 → 工具调用 → Observation → 继续推理 → Final Answer

同时保留同一个会话的上下文，实现多轮对话。

---

## 2. 目录职责

```text
react_financial_agent/
├── src/
│   ├── tools.py          # 工具实现
│   ├── react_manual.py   # 唯一的 agent 核心逻辑
│   ├── agent.py          # CLI 入口
│   └── serve.py          # Web 服务入口
├── index.html            # Web UI
├── USAGE_GUIDE.md        # 使用说明
└── ARCHITECTURE.md      # 本文件
```

已移除：

- 旧的双实现
- 对比评估脚本
- 双模式入口

---

## 3. 核心数据流

### 单轮执行

1. 用户输入一个问题
2. Agent 读取 `messages`
3. LLM 决定是直接回答，还是调用一个工具
4. 工具返回 Observation
5. Observation 写回 `messages`
6. 直到输出 `Final Answer`

### 多轮对话

同一个 `messages` 列表会跨轮复用，因此：

- 上轮问答会保留
- 上轮的工具轨迹会保留
- 下一轮可以直接引用上文

---

## 4. 工具集

| 工具 | 用途 |
|---|---|
| `rag_search` | 年报语义检索 |
| `company_lookup` | 公司名转股票代码 |
| `calculator` | 数学计算 |
| `financial_indicator` | 财务指标查询 |
| `stock_price` | 历史股价查询 |

---

## 5. 代码结构

### `react_manual.py`

唯一的 agent 核心模块，负责：

- 系统提示词
- 输出解析
- 工具调用循环
- 会话消息维护
- CLI 交互式对话

### `agent.py`

统一命令行入口：

- `python agent.py --question "..."`
- `python agent.py --chat`

### `serve.py`

FastAPI 服务：

- `POST /query`
- `POST /reset`
- `GET /health`

---

## 6. 取舍

为什么只保留一个主流程：

- 代码路径更短，维护成本更低
- 不再需要两套并行实现对比
- 对用户来说，行为更一致
- 多轮对话可以直接建立在同一条推理链上
