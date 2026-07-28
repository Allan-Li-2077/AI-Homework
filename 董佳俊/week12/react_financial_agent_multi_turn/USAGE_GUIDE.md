# USAGE_GUIDE.md — 多轮对话 ReAct Financial Agent 使用指南

## 1. 环境准备

### 安装依赖
```bash
pip install openai faiss-cpu akshare fastapi uvicorn numpy
```

### 配置 API Key

**必填**：DashScope API Key（LLM 推理 + RAG Embedding 共用）

```bash
# Linux / macOS
export DASHSCOPE_API_KEY="sk-xxx"
export AGENT_MODEL="qwen-max"           # 可选，默认 qwen-max

# Windows PowerShell
$env:DASHSCOPE_API_KEY = "sk-xxx"
$env:AGENT_MODEL = "qwen-max"
```

> **注意**：`react_function_calling.py` 默认使用 DeepSeek API（`deepseek-v4-flash`），需额外设置 `DEEPSEEK_API_KEY`。如需切换回 DashScope，取消文件中的注释即可。详见第 5 节。

### 验证环境
```bash
cd react_financial_agent_multi_turn/src
python -c "from tools import TOOLS_MAP; print('工具加载成功，共', len(TOOLS_MAP), '个')"
```

---

## 2. 三种使用方式

### 2.1 CLI 单轮模式（兼容旧版）

```bash
cd react_financial_agent_multi_turn/src

# 手写 Prompt 解析版（默认）
python agent.py --mode manual --question "茅台和五粮液2023年毛利率差多少？"

# Function Calling 版
python agent.py --mode fc --question "宁德时代2023年营业收入是多少？"

# 指定最大步数
python agent.py --mode manual --question "..." --max_steps 8
```

### 2.2 CLI 交互模式 ★ 多轮对话

```bash
cd react_financial_agent_multi_turn/src

# 手写版交互模式
python agent.py --mode manual --interactive

# FC 版交互模式
python agent.py --mode fc --interactive
```

**交互命令**：

| 输入 | 效果 |
|------|------|
| 正常问题 | 发送给 Agent，保留对话历史 |
| `/clear` | 清空对话历史，开始新对话 |
| `/history` | 查看当前对话轮数 |
| `exit` / `quit` | 退出交互模式 |

**交互示例**：

```
============================================================
  ReAct Financial Agent - 交互模式
  模型: qwen-max    实现: 手写Prompt解析
  /clear  清空对话历史
  /history  查看当前对话轮数
  exit / quit  退出
============================================================

[1] >> 贵州茅台2023年毛利率是多少？

[Step 1]
🧠 Thought: 需要先获取茅台股票代码...
🔧 Action:  company_lookup
   Input:   {"name": "贵州茅台"}
👁  Obs:     贵州茅台 的股票代码为 600519

[Step 2]
🧠 Thought: 现在获取茅台财务指标...
🔧 Action:  financial_indicator
   Input:   {"symbol": "600519"}
👁  Obs:     毛利率: 2023年: 91.96 | ...

✅ Final Answer:
贵州茅台2023年毛利率为91.96%

共 2 步，耗时 32.1s

[2] >> 那五粮液的呢？           ← 多轮对话：自动理解"那...呢"指的是毛利率

[Step 1]
🧠 Thought: 用户追问五粮液毛利率，先查代码...
🔧 Action:  company_lookup
   Input:   {"name": "五粮液"}
...

✅ Final Answer:
五粮液2023年毛利率为75.79%
```

### 2.3 Web UI 模式 ★ 推荐演示

```bash
cd react_financial_agent_multi_turn/src
uvicorn serve:app --host 0.0.0.0 --port 8001
```

启动后，浏览器访问 **http://localhost:8001**（不要直接双击 index.html 文件）。

**页面功能**：
- 🔄 **模式切换**：手写 Prompt 解析 / Function Calling
- 💬 **多轮对话**：提问后不覆盖历史，每次追加新的对话轮次
- 📂 **步骤折叠**：点击 Step 标题可展开/折叠推理细节
- 🆕 **新对话按钮**：清空历史，生成新 session
- 📌 **示例问题**：点击即可填入预设问题

**多轮对话演示流程**：

```
第 1 轮：茅台2023年毛利率是多少？
第 2 轮：那五粮液的呢？            ← Agent 自动理解指代五粮液的毛利率
第 3 轮：帮我算一下两家差多少      ← Agent 引用前面已经获取过的数据
第 4 轮：点击 "新对话" 按钮        ← 开始全新对话
```

---

## 3. API 接口说明

### 3.1 基础接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查（含活跃 session 数） |
| `GET` | `/` | Web 页面 |

### 3.2 Session 管理

| 方法 | 路径 | 请求体 | 说明 |
|------|------|--------|------|
| `POST` | `/session/create` | `{"mode": "manual"}` | 创建新 session，返回 session_id |
| `POST` | `/session/delete` | `{"session_id": "abc123"}` | 删除指定 session |

### 3.3 Query 接口（SSE 流式）

| 方法 | 路径 | 请求体 | 说明 |
|------|------|--------|------|
| `POST` | `/query/manual` | `{"question": "...", "session_id": null}` | 手写版，session_id 为空时自动创建 |
| `POST` | `/query/fc` | `{"question": "...", "session_id": "abc123"}` | FC 版，传入已有 session_id 继续对话 |

**SSE 事件格式**：

```json
// 1. 返回 session ID
{"type": "session_start", "session_id": "a1b2c3d4e5f6"}

// 2. 每步推理
{"type": "action", "step": 1, "thought": "...", "action": "company_lookup", "action_input": {"name": "茅台"}, "observation": "股票代码为 600519"}

// 3. 最终答案
{"type": "final", "step": 5, "thought": "已有足够信息", "answer": "茅台毛利率91.96%..."}

// 4. 完成标记
{"type": "done"}
```

---

## 4. 作为模块调用（Python）

```python
import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ["DASHSCOPE_API_KEY"] = "sk-xxx"

import sys
sys.path.insert(0, "react_financial_agent_multi_turn/src")

# ── 单轮调用（向后兼容） ──────────────────────────────────
from react_manual import run

for step in run("茅台2023年毛利率是多少？", max_steps=10):
    if step["type"] == "action":
        print(f"Step {step['step']}: {step['action']} → {step['observation'][:100]}")
    elif step["type"] == "final":
        print(f"Answer: {step['answer']}")
    elif step["type"] == "session_messages":
        messages = step["messages"]   # 保留给下一轮

# ── 多轮调用 ──────────────────────────────────────────────
messages = None  # 第一轮从零开始

# 第一轮
for step in run("茅台2023年毛利率是多少？", messages=messages):
    if step["type"] == "session_messages":
        messages = step["messages"]

# 第二轮（带上第一轮的完整对话历史）
for step in run("那五粮液的呢？", messages=messages):
    if step["type"] == "session_messages":
        messages = step["messages"]

# FC 版用法完全一致
from react_function_calling import run as fc_run
```

---

## 5. 模型切换

### 手写版（react_manual.py）— 默认 qwen-max

```python
# 文件顶部已有注释好的 DeepSeek 配置
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)
MODEL = os.getenv("AGENT_MODEL", "deepseek-v3")
```

### FC 版（react_function_calling.py）— 默认 deepseek-v4-flash

```python
# 文件顶部已有注释好的 DashScope 配置
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
MODEL = os.getenv("AGENT_MODEL", "qwen-max")
```

---

## 6. 调试与常见问题

**Q: Web UI 显示 "请求失败: Failed to fetch"**

A: 你直接双击打开了 `index.html` 文件，浏览器使用 `file://` 协议，无法请求 `/query/manual`。正确做法是：
1. 先启动服务：`uvicorn serve:app --host 0.0.0.0 --port 8001`
2. 再访问 `http://localhost:8001`

**Q: `rag_search` 报错 `assert d == self.d`**

A: Embedding 维度不匹配。确认 `DASHSCOPE_API_KEY` 已设置。`rag_search` 使用 DashScope `text-embedding-v3`（1024 维）编码查询，与建索引时保持一致。

**Q: Session 过期了怎么办？**

A: Session 默认 30 分钟 TTL。过期后服务端自动创建新 session，前端通过 `session_start` 事件自动获取新 ID，对用户透明。

**Q: 对话历史会无限增长吗？**

A: 服务端每 5 分钟清理一次过期 session（30 分钟无活动）。CLI 交互模式下可用 `/clear` 手动清空。

**Q: 手写版和 FC 版能混用同一个 session 吗？**

A: 不建议。两个版本的 System Prompt 和消息格式不同，混用会导致模型困惑。前端切换模式时会自动创建新 session。

**Q: 端口冲突怎么办？**

A: 代码默认 8001，与原项目 8000 不冲突。如需修改：
```bash
uvicorn serve:app --host 0.0.0.0 --port 9000
```
同时修改 `index.html` 中 fetch 的端口。
