# ARCHITECTURE.md — ReAct AI Tech Agent 技术方案

## 1. 项目定位

本项目以 AI 技术问答为场景，落地 **ReAct（Reasoning + Acting）** Agent 范式。

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
| `ai_concept_lookup` | 静态字典 | AI概念定义查询，防幻觉 | `name="Transformer"` |
| `rag_search` | FAISS + DashScope Embedding | AI论文语义检索，技术细节 | `query="注意力机制原理"` |
| `paper_summary` | FAISS + DashScope Embedding | 论文摘要检索 | `title="Attention Is All You Need"` |
| `concept_compare` | 静态字典 | 两个AI概念对比 | `concept1="Transformer"`, `concept2="RNN"` |
| `calculator` | Python eval（受限沙箱） | 数学计算 | `expr="512 * 512"` |

### 3.2 工具设计原则

**`ai_concept_lookup` 是基础工具**：提供 AI 核心概念的标准化定义，防止模型幻觉，作为其他工具的前置知识补充。

**`rag_search` 与 `paper_summary` 的张力**：两者都检索论文内容，但 `rag_search` 适合查询具体技术细节，`paper_summary` 专注于摘要信息。Agent 自主决策用哪个，体现推理价值。

**`concept_compare` 支持对比分析**：直接对比两个概念的异同，适合面试中常见的对比类问题。

**`calculator` 防心算漂移**：LLM 做多位小数运算容易出错，强制走工具确保数字准确。

### 3.3 RAG 索引说明

- 数据：AI 技术论文（如 Attention Is All You Need 等），共约 10000+ 条向量
- Embedding 模型：DashScope `text-embedding-v3`（1024维），与建索引时保持一致
- 索引：FAISS IndexFlatIP，复用自 AI 技术知识库项目

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

## 5. 多轮对话支持

Agent 支持多轮对话能力，通过 `conversation_history` 参数传递历史对话：

```python
conversation_history = [
    {"question": "Transformer是什么？", "answer": "Transformer是..."},
    {"question": "它的注意力机制是怎样的？", "answer": "注意力机制..."}
]
```

在每次调用时，历史对话会被追加到消息列表中，使模型能够理解上下文并保持对话连续性。

---

## 6. 实验结果（手写版示例运行）

**问题**：Transformer和RNN的主要区别是什么？

| 步骤 | Action | 关键 Observation |
|------|--------|-----------------|
| 1 | `concept_compare("Transformer", "RNN")` | 返回两者对比信息 |
| Final | — | Transformer基于注意力机制，RNN基于循环连接... |

---

## 7. 消融方向建议

| 实验 | 操作 | 观察点 |
|------|------|--------|
| 去掉 `ai_concept_lookup` | 直接回答概念问题 | Agent 会产生幻觉，观察错误恢复能力 |
| 去掉 `stop=["Observation:"]` | 让模型自己编造 Observation | 幻觉对比，教学价值高 |
| 换 `qwen-turbo` | 修改 `AGENT_MODEL` 环境变量 | 格式稳定性下降，parse_errors 增加 |
| 换 `deepseek-v3` | 修改 `base_url` 和 `AGENT_MODEL` | 与 qwen-max 对比格式稳定性 |

---

## 8. 关键工程决策与踩坑

| 问题 | 根因 | 解法 |
|------|------|------|
| FAISS search 报 `assert d == self.d` | 索引用 DashScope text-embedding-v3（1024维），本地 bge-small 为512维 | rag_search 统一改用 DashScope embedding API，与建索引时保持一致 |
| Windows OpenMP 冲突 | torch 与 numpy 各自链接 libiomp5md.dll | 所有脚本顶部加 `os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")` |
| Thought 为空字符串 | qwen-max 在第2步后有时不输出 Thought，直接输出 Action | 正则解析容忍 Thought 缺失，不影响循环继续 |

---

## 9. 目录结构

```
react_ai_tech_agent/
├── src/
│   ├── tools.py                  # 5个工具实现（rag/concept/paper/calc/compare）
│   ├── react_manual.py           # 手写Prompt解析版 ReAct
│   ├── react_function_calling.py # Function Calling版 ReAct
│   ├── agent.py                  # 统一入口，--mode manual/fc 切换
│   ├── evaluate.py               # 两种实现对比评估
│   └── serve.py                  # FastAPI HTTP服务
├── vectorstore/
│   ├── faiss_index.bin           # FAISS索引（1024维，~10000+条）
│   └── faiss_meta.json           # 向量对应的chunk元数据
├── models/
│   └── bge-small-zh-v1.5/        # 本地 Embedding 模型（512维，当前未使用）
├── index.html                    # Web UI，流式展示每步循环
├── requirements.txt
├── ARCHITECTURE.md               # 本文件
├── USAGE_GUIDE.md
└── RESUME_GUIDE.md
```