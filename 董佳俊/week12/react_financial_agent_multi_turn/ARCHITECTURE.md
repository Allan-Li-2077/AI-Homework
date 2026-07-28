# ARCHITECTURE.md — 多轮对话 ReAct Financial Agent 技术方案

## 1. 项目定位

本项目在[原单轮 ReAct Agent](../react_financial_agent/) 基础上，**增加多轮对话能力**。核心改动：让 Agent 记住前几轮的问答内容，理解"那另一家呢？"这类指代性追问。

与原项目的关系：
- **不动原项目**：所有改动在新目录 `react_financial_agent_multi_turn/` 中
- **向后兼容**：`run()` 不传 `messages` 参数时，行为与原版完全一致
- **端口隔离**：Web 服务默认 8001（原项目 8000）

---

## 2. 多轮对话架构

```
第 1 轮请求 (session_id = None)
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  serve.py: 创建 Session，记录 messages              │
│                                                     │
│  session.messages = [system, user_q1, ...]          │
└─────────────────────────────────────────────────────┘
    │ 返回 session_id + final_answer
    ▼
第 2 轮请求 (带上 session_id)
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  serve.py: 取出 session.messages                    │
│                                                     │
│  run(question=q2, messages=prior_messages)          │
│    → messages = [system, user_q1, ..., user_q2]     │
│    → 模型能看到上一轮的完整上下文                  │
│                                                     │
│  更新 session.messages                              │
└─────────────────────────────────────────────────────┘
```

**关键设计决策**：保留完整 messages 列表（含 system/user/assistant/tool 消息），不做摘要压缩。模型能直接引用之前的工具调用结果，避免重复查询。

---

## 3. 核心改动对比

| 维度 | 原版（单轮） | 多轮版 |
|------|-------------|--------|
| `run()` 签名 | `(question, max_steps)` | `(question, max_steps, messages=None)` |
| messages 构建 | 每次 `[system, user_q]` | 有历史时 `[...history, user_q]` |
| 循环退出 | `return` 直接返回 | `break` 后统一落到末尾 |
| 状态传递 | 无 | `yield {"type": "session_messages", "messages": messages}` |
| 服务端 | 无状态 | Session dict + TTL 管理 |
| CLI | 单次执行 | `--interactive` REPL 循环 |
| Web UI | 每次清空容器 | 追加 `.conversation-turn` |

---

## 4. session_messages 机制

这是多轮对话架构的**核心胶水代码**。设计要点：

```python
# run() 函数末尾（所有退出路径之后）
yield {"type": "session_messages", "messages": messages}
```

**为什么不用 return 值？**

`run()` 是 Generator，调用方通过 `for step in run(...)` 消费。要让调用方拿到最终的 messages 列表，有两种选择：
1. 要求调用方用 `send()` 交互 → 侵入性强，不直观
2. 多 yield 一个特殊类型的事件 → 兼容性好，旧代码自动忽略

选择了方案 2：`session_messages` 类型的事件对 `run_and_print()` 和 `evaluate.py` 不可见（被 `continue` 跳过），但 `serve.py` 和 `agent.py`（交互模式）会捕获并保存。

---

## 5. Session 管理

### 5.1 数据结构

```python
@dataclass
class Session:
    session_id: str        # uuid.hex[:12]，如 "a1b2c3d4e5f6"
    messages: list         # 完整对话历史
    mode: str              # "manual" 或 "fc"
    created_at: datetime   # 创建时间
    last_active: datetime  # 最后活跃时间（用于 TTL 判断）
```

### 5.2 生命周期

```
创建 ──→ 活跃（每次请求更新 last_active）
                  │
                  ├── 30 分钟无活动 ──→ 过期清理（每 5 分钟扫描）
                  │
                  └── 用户点"新对话" ──→ 客户端生成新 session_id，旧 session 自然过期
```

### 5.3 并发安全

`asyncio.Lock` 保护 SESSIONS 字典的读写。worker 线程通过 `queue.put_nowait()` 写入结果，异步事件循环消费时获取锁更新 session.messages。

---

## 6. 文件改动清单

| 文件 | 行数变化 | 改动性质 |
|------|---------|---------|
| `src/react_manual.py` | +25 行 | `run()` 增加 `messages` 参数；`return` → `break`；末尾 `yield session_messages`；System Prompt 增加多轮提示；`run_and_print` 跳过内部事件 |
| `src/react_function_calling.py` | +25 行 | 同 manual 版模式 |
| `src/serve.py` | +90 行 | Session dataclass + 全局存储 + CRUD 路由 + `_stream_react` 改造 + 定期清理任务 |
| `src/agent.py` | +65 行 | `--interactive` 参数 + REPL 循环 + `/clear` `/history` 命令 + 显示逻辑提取 |
| `index.html` | +120 行 | Session 管理（localStorage）+ 对话轮次 UI + 新对话按钮 + 用户气泡样式 |
| `src/tools.py` | 0 行 | 直接复制，无改动 |
| `src/evaluate.py` | 0 行 | 直接复制，无改动（`session_messages` 事件不影响其过滤逻辑） |

---

## 7. 多轮对话效果示例

**问题序列**（同一 session）：

```
Q1: 贵州茅台2023年毛利率是多少？
    → Agent: company_lookup → financial_indicator → 91.96%

Q2: 那五粮液的呢？
    → Agent 理解"那...呢"指毛利率
    → company_lookup("五粮液") → financial_indicator("000858") → 75.79%

Q3: 帮我算一下具体差多少
    → Agent 引用前两步已经获取的数据
    → calculator("91.96 - 75.79") → 16.17 个百分点

Q4: 这两家公司的股价表现呢？
    → Agent 理解"这两家"指茅台、五粮液
    → stock_price("600519", ...) → stock_price("000858", ...) → 对比
```

**关键体现**：Q2-Q4 都依赖 Q1 建立的上下文（公司名→代码映射、已获取的财务数据），Agent 不再重复查询已有数据，直接推理并调用新工具。

---

## 8. 目录结构

```
react_financial_agent_multi_turn/
├── src/
│   ├── tools.py                  # 5 个工具（rag/financial/stock/calc/lookup）
│   ├── react_manual.py           # 手写 Prompt 解析版（支持 messages 历史）
│   ├── react_function_calling.py # Function Calling 版（支持 messages 历史）
│   ├── agent.py                  # 统一入口，--interactive 多轮交互
│   ├── evaluate.py               # 两种实现对比评估
│   └── serve.py                  # FastAPI + Session 管理 + SSE 流式
├── vectorstore/
│   ├── faiss_index.bin           # FAISS 索引（1024 维，10353 条）
│   └── faiss_meta.json           # chunk 元数据
├── index.html                    # Web UI（多轮对话）
├── requirements.txt
├── ARCHITECTURE.md               # 本文件
└── USAGE_GUIDE.md                # 使用指南
```
