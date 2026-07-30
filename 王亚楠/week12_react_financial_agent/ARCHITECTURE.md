# ARCHITECTURE.md — ReAct Financial Agent 技术方案

## 1. 项目定位

本项目以 A 股金融分析为场景，落地 **ReAct（Reasoning + Acting）** Agent 范式。

核心教学目标：
- 理解 ReAct 的本质：Thought → Action → Observation 循环，推理与行动交替驱动
- 对比两种工程实现：手写 Prompt 解析 vs Function Calling API
- 体会工具异构性的价值：同一 Agent，同一问题，不同工具组合路径不同

### 方案对比表

| 维度 | 手写 Prompt 解析 | Function Calling API |
|------|----------------|----------------------|
| Thought 可见性 | 完全可见，正则解析 | 模型内部，不可见 |
| 格式稳定性 | 依赖 Prompt 工程，偶有漂移 | 原生结构化，格式稳定 |
| 代码量 | ~150 行核心逻辑 | ~80 行核心逻辑 |
| 可控性 | 高，可定制停止词和格式 | 低，依赖模型实现 |
| 教学价值 | 高，学生能看见每一步 | 次之，适合生产场景 |

---

## 2. 整体流水线

```
用户问题
    │
    ▼
┌─────────────────────────────────────────────────────┐
│               ReAct 循环（最多 10 步）               │
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐   │
│  │  Thought  │──▶│  Action  │──▶│ Observation  │   │
│  │ LLM 推理  │   │ 工具调用  │   │  工具返回结果  │   │
│  └──────────┘   └──────────┘   └──────┬───────┘   │
│       ▲                                │           │
│       └────────────────────────────────┘           │
│                      循环                           │
└─────────────────────────────────────────────────────┘
    │ Final Answer
    ▼
Web UI 展示 / CLI 打印

脚本对应：
  react_manual.py          手写Prompt解析版核心循环
  react_function_calling.py Function Calling版核心循环
  tools.py                 5个工具实现
  agent.py                 统一入口
  serve.py                 FastAPI服务
  index.html               Web UI
  evaluate.py              两种实现对比评估
```

---

## 3. 工具集设计

### 3.1 工具一览

| 工具名 | 数据来源 | 核心用途 | 典型参数 |
|--------|---------|---------|---------|
| `company_lookup` | 静态字典 | 公司名→股票代码，防幻觉 | `name="贵州茅台"` |
| `rag_search` | FAISS + DashScope Embedding | 年报语义检索，定性内容 | `query="茅台毛利率"` |
| `financial_indicator` | AkShare `stock_financial_abstract` | 近3年结构化财务指标 | `symbol="600519"` |
| `stock_price` | AkShare `stock_zh_a_hist` | 历史股价与区间涨跌幅 | `symbol, start_date, end_date` |
| `calculator` | Python eval（受限沙箱） | 四则运算、百分比、CAGR | `expr="91.96-75.79"` |
| `memory_search` | MemoryStore | 搜索记忆中的事实和历史对话 | `query="茅台"` |
| `memory_save` | MemoryStore | 主动保存信息到记忆库 | `key, content` |

### 3.2 工具设计原则

**`company_lookup` 是必要的第一步**：没有它，Agent 会把"贵州茅台"直接传入股价接口报错。设计成显式工具后，Thought 里会出现"先查代码"的推理，循环更自然。

**`rag_search` 与 `financial_indicator` 的张力**：两者都能返回财务数字，但 RAG 来自 PDF 原文（定性描述更丰富），AkShare 来自结构化数据（跨年对比更可靠）。Agent 自主决策用哪个，体现推理价值。

**`calculator` 防心算漂移**：LLM 做多位小数运算容易出错，强制走工具确保数字准确，同时让计算步骤可见。

### 3.3 RAG 索引说明

- 数据：5家公司（贵州茅台/五粮液/宁德时代/中国平安/海康威视）2021-2023 年报，共 15 份 PDF
- Embedding 模型：DashScope `text-embedding-v3`（1024维），与建索引时保持一致
- 索引：FAISS IndexFlatIP，10353 条向量，复用自 `rag_annual_report` 项目

---

## 4. 两种实现对比

### 4.1 手写 Prompt 解析版（react_manual.py）

**System Prompt 约束格式**：
```
Thought: 分析当前状态...
Action: 工具名称
Action Input: {"参数名": "参数值"}
```

**停止词**：`stop=["Observation:"]`，让模型在调用工具前停止，由 Python 执行工具后再追加 Observation 继续对话。

**解析逻辑**：
```python
_THOUGHT_RE      = re.compile(r"Thought:\s*(.+?)(?=\nAction:|\nFinal Answer:|$)", re.DOTALL)
_ACTION_RE       = re.compile(r"Action:\s*(\w+)")
_ACTION_INPUT_RE = re.compile(r"Action Input:\s*(\{.+?\})", re.DOTALL)
_FINAL_RE        = re.compile(r"Final Answer:\s*(.+)", re.DOTALL)
```

**优点**：Thought 完全可见，每步透明，适合教学。
**缺点**：模型偶尔输出格式不规范，parse_errors > 0。

### 4.2 Function Calling 版（react_function_calling.py）

**工具注册**：`TOOLS_SCHEMA` 中每个工具提供 JSON Schema，模型原生理解参数结构。

**循环判断**：
```python
if reason == "stop" or not msg.tool_calls:
    # 模型决定直接回答，循环结束
else:
    # 执行 tool_calls，追加 tool 角色消息继续
```

**缺点**：Thought 在模型内部不可见，Web UI 中以灰色提示展示。

---

## 5. 实验结果（手写版示例运行）

**问题**：贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？

| 步骤 | Action | 关键 Observation |
|------|--------|-----------------|
| 1 | `company_lookup("贵州茅台")` | 600519 |
| 2 | `company_lookup("五粮液")` | 000858 |
| 3 | `financial_indicator("600519")` | 茅台2023毛利率 91.96% |
| 4 | `financial_indicator("000858")` | 五粮液2023毛利率 75.79% |
| 5 | `calculator("91.96 - 75.79")` | 16.17 |
| Final | — | 茅台高出五粮液16.17个百分点 |

耗时约 67s，5步工具调用 + 1步 Final Answer。

---

## 6. 消融方向建议

| 实验 | 操作 | 观察点 |
|------|------|--------|
| 去掉 `company_lookup` | 直接传公司名给 AkShare | Agent 会报错，观察错误恢复能力 |
| 去掉 `stop=["Observation:"]` | 让模型自己编造 Observation | 幻觉对比，教学价值高 |
| 换 `qwen-turbo` | 修改 `AGENT_MODEL` 环境变量 | 格式稳定性下降，parse_errors 增加 |
| 换 `deepseek-v3` | 修改 `base_url` 和 `AGENT_MODEL` | 与 qwen-max 对比格式稳定性 |

---

## 7. 关键工程决策与踩坑

| 问题 | 根因 | 解法 |
|------|------|------|
| FAISS search 报 `assert d == self.d` | 索引用 DashScope text-embedding-v3（1024维），本地 bge-small 为512维 | rag_search 统一改用 DashScope embedding API，与建索引时保持一致 |
| `akshare.stock_a_lg_indicator` 不存在 | AkShare 1.10+ 改名或移除了该接口 | 改用 `stock_financial_abstract`，字段更丰富，响应更快 |
| Windows OpenMP 冲突 | torch 与 numpy 各自链接 libiomp5md.dll | 所有脚本顶部加 `os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")` |
| Thought 为空字符串 | qwen-max 在第2步后有时不输出 Thought，直接输出 Action | 正则解析容忍 Thought 缺失，不影响循环继续 |

---

## 8. 目录结构

```
react_financial_agent/
├── src/
│   ├── tools.py                  # 7个工具实现（5个金融 + 2个记忆）
│   ├── memory.py                 # 记忆系统 — MemoryStore 持久化层
│   ├── chat.py                   # 循环对话 — ChatSession 多轮管理
│   ├── react_manual.py           # 手写Prompt解析版 ReAct
│   ├── react_function_calling.py # Function Calling版 ReAct
│   ├── agent.py                  # 统一入口，--mode manual/fc 切换 + 记忆管理
│   ├── evaluate.py               # 两种实现对比评估
│   └── serve.py                  # FastAPI HTTP服务 + 记忆管理API
├── memory/                       # 记忆数据存储
│   ├── conversations/            # 按 session 组织的对话历史
│   └── facts.json                # 事实知识库
├── vectorstore/
│   ├── faiss_index.bin           # FAISS索引（1024维，10353条，~41MB）
│   └── faiss_meta.json           # 向量对应的chunk元数据（~15MB）
├── index.html                    # Web UI，流式展示每步循环 + 记忆面板
├── requirements.txt
├── ARCHITECTURE.md               # 本文件
├── USAGE_GUIDE.md
└── RESUME_GUIDE.md
```

---

## 9. 记忆系统设计

### 9.1 概述

记忆系统为 Agent 提供跨查询的持久化能力，解决每次查询独立运行、无法复用历史分析结果的问题。

**两层记忆**：

| 层级 | 存储 | 内容 | 生命周期 |
|------|------|------|---------|
| Conversation Memory | `memory/conversations/{session_id}.json` | Q&A 对话、步骤、工具调用 | 持久化，按 session 隔离 |
| Fact Memory | `memory/facts.json` | 提取的关键事实（股票代码映射、财务数据等） | 持久化，跨 session 共享 |

### 9.2 工作流程

```
用户提问
    │
    ├── 1. 加载记忆上下文 ── 从 Fact Memory 匹配相关事实
    │                       从 Conversation Memory 加载近期对话
    │
    ├── 2. 注入 System Prompt ── 记忆上下文追加到 System Prompt
    │
    ├── 3. ReAct 循环 ── Agent 可以使用 memory_search / memory_save 工具
    │
    ├── 4. 自动提取事实 ── 正则匹配 Observation 中的关键信息
    │
    └── 5. 持久化对话 ── 保存到 Conversation Memory
```

### 9.3 自动事实提取

在每次对话保存时，自动从 Observation 中提取：

- `"XX 的股票代码为 XXXXXX"` → 写入 `facts.json` 的 `股票代码:XX` 键
- 后续查询时，记忆系统发现"茅台"出现在问题中 → 自动注入 `股票代码:茅台 = 600519` → Agent 可跳过 `company_lookup`

### 9.4 记忆工具

Agent 可主动调用两个记忆工具：

- **`memory_search(query)`** — 搜索记忆库中的事实和历史对话
- **`memory_save(key, content)`** — 主动保存重要信息（如计算结果、分析结论）

这使得 Agent 能够在需要时查阅"过去的自己"。

### 9.5 管理接口

| 接口 | 说明 |
|------|------|
| `python agent.py --list-sessions` | 列出所有会话 |
| `python agent.py --clear-memory` | 清空全部记忆 |
| `python agent.py --no-memory` | 禁用记忆（向后兼容） |
| `python agent.py --session-id my_session` | 指定会话 ID |
| `GET /memory/stats` | Web API: 记忆统计 |
| `GET /memory/sessions` | Web API: 会话列表 |
| `DELETE /memory/session/{id}` | Web API: 删除会话 |
| `DELETE /memory` | Web API: 清空全部记忆 |

### 9.6 设计原则

- **非侵入式**: `run()` 签名新增可选参数 `memory`，不传则行为不变
- **文件持久化**: JSON 文件，零外部依赖
- **Agent 可主动读写**: 记忆以工具形式暴露，Agent 自主决策何时使用
- **自动提取 + 手动保存**: 股票代码等结构化信息自动提取，复杂结论由 Agent 主动保存
