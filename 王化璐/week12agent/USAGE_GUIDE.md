# USAGE_GUIDE.md — AI 技术问答 Agent 使用指南

## 1. 环境准备

### 安装依赖
```bash
pip install openai faiss-cpu fastapi uvicorn numpy
```

### 配置 API Key
```bash
export DASHSCOPE_API_KEY="sk-xxx"       # 必填，用于 LLM 推理和 RAG Embedding
export AGENT_MODEL="qwen-max"           # 可选，默认 qwen-max，可换 deepseek-v3 等
```

Windows PowerShell：
```powershell
$env:DASHSCOPE_API_KEY = "sk-xxx"
$env:AGENT_MODEL = "qwen-max"
```

---

## 2. 各脚本使用说明

### 2.1 agent.py — 统一命令行入口

```bash
cd ai_tech_interview_agent/src

# 手写 Prompt 解析版（默认）
python agent.py --mode manual --question "Transformer的注意力机制是什么？"

# Function Calling 版
python agent.py --mode fc --question "BERT和GPT有什么区别？"

# 调整最大步数（默认10）
python agent.py --mode manual --question "..." --max_steps 8
```

**预期输出**（手写版）：
```
============================================================
问题: Transformer和RNN的主要区别是什么？
模型: qwen-max  实现: 手写Prompt解析
============================================================

[Step 1]
🧠 Thought: 需要对比Transformer和RNN两个概念...
🔧 Action:  concept_compare
   Input:   {"concept1": "Transformer", "concept2": "RNN"}
👁  Obs:     【Transformer】
  类型: 架构 | 年份: 2017
...
✅ Final Answer:
Transformer和RNN的主要区别在于...
```

---

### 2.2 react_manual.py — 手写版独立运行

```bash
python react_manual.py
python react_manual.py --question "Attention Is All You Need论文的核心贡献是什么？"
```

**内部流程**：
1. 构造含工具描述的 System Prompt
2. 调用 LLM，`stop=["Observation:"]` 让模型在工具调用前停止
3. 正则解析 Thought / Action / Action Input
4. 执行工具，获取 Observation
5. 将 Observation 追加到对话历史，继续下一步
6. 检测到 `Final Answer:` 时终止

---

### 2.3 react_function_calling.py — Function Calling 版独立运行

```bash
python react_function_calling.py
python react_function_calling.py --question "BERT模型的关键技术点有哪些？"
```

**与手写版的关键区别**：
- 工具通过 JSON Schema（`TOOLS_SCHEMA`）注册给模型
- 模型通过 `tool_calls` 字段返回工具调用请求，格式由 API 保证
- Thought 过程在模型内部，CLI/UI 中显示为灰色提示

---

### 2.4 evaluate.py — 对比评估

```bash
python evaluate.py
python evaluate.py --output ../evaluation/compare_result.json
```

**评估问题集**（5题）：
- Q1: 概念对比（Transformer vs RNN）
- Q2: 论文摘要检索（Attention Is All You Need）
- Q3: 概念查询（BERT关键技术点）
- Q4: 论文细节检索（多头注意力机制工作原理）
- Q5: 边界拒绝（预测未来AI发展，应拒绝）

**输出示例**：
```
ID   Mode     Steps   Time(s)   Success  ParseErr
──────────────────────────────────────────────────
Q1   manual   1       15.0      True     0
Q1   fc       1       12.0      True     0
...
[manual] 平均步数:2.0  平均耗时:25.0s  成功率:80%  解析错误总数:0
[fc]     平均步数:2.0  平均耗时:20.0s  成功率:80%  解析错误总数:0
```

---

### 2.5 serve.py — Web 服务启动

```bash
cd ai_tech_interview_agent/src
uvicorn serve:app --host 0.0.0.0 --port 8000
```

启动后访问：http://localhost:8000

**接口列表**：
- `GET  /health` — 健康检查
- `POST /query/manual` — 手写版 ReAct，流式 SSE 返回每步
- `POST /query/fc` — Function Calling 版，流式 SSE 返回每步

**SSE 事件格式**：
```json
{"type": "start",  "question": "...", "mode": "manual"}
{"type": "action", "step": 1, "thought": "...", "action": "concept_compare", "action_input": {...}, "observation": "..."}
{"type": "final",  "step": 2, "thought": "...", "answer": "..."}
{"type": "done"}
```

**多轮对话请求示例**：
```json
{
  "question": "它的注意力机制是怎样工作的？",
  "max_steps": 10,
  "conversation_history": [
    {"question": "Transformer是什么？", "answer": "Transformer是基于注意力机制的序列建模架构..."}
  ]
}
```

---

## 3. 作为模块调用

```python
import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import sys
sys.path.insert(0, "ai_tech_interview_agent/src")

# 手写版
from react_manual import run as manual_run

for step in manual_run("Transformer的注意力机制是什么？", max_steps=10):
    if step["type"] == "action":
        print(f"Step {step['step']}: {step['action']}({step['action_input']})")
        print(f"  => {step['observation'][:100]}")
    elif step["type"] == "final":
        print(f"Final: {step['answer']}")

# Function Calling 版（接口完全一致）
from react_function_calling import run as fc_run
for step in fc_run("BERT和GPT的区别？"):
    ...

# 多轮对话示例
history = [
    {"question": "Transformer是什么？", "answer": "Transformer是基于注意力机制的架构..."},
]
for step in manual_run("它的核心创新是什么？", conversation_history=history):
    ...
```

---

## 4. 工具单独调用

```python
from tools import TOOLS_MAP

# AI概念查询
print(TOOLS_MAP["ai_concept_lookup"](name="Transformer"))
# => 概念: Transformer
#    类型: 架构
#    年份: 2017
#    描述: 基于注意力机制的序列建模架构...

# 计算器
print(TOOLS_MAP["calculator"](expr="512 * 512"))
# => 262144

# 论文检索
print(TOOLS_MAP["rag_search"](query="注意力机制原理", top_k=3))
# => [1] 来源：Attention Is All You Need (2017) ...

# 论文摘要
print(TOOLS_MAP["paper_summary"](title="Attention Is All You Need"))
# => 论文: Attention Is All You Need (2017)
#    内容: The dominant sequence transduction models...

# 概念对比
print(TOOLS_MAP["concept_compare"](concept1="Transformer", concept2="RNN"))
# => 【Transformer】
#    ...
#    【RNN】
#    ...
#    【对比分析】
```

---

## 5. 调试与常见问题

**Q: `rag_search` 报错 `assert d == self.d`**
A: Embedding 维度不匹配。确认 `DASHSCOPE_API_KEY` 已设置，`rag_search` 使用 DashScope API 编码查询，与建索引时保持 1024 维一致。

**Q: Web UI 显示"请求失败"**
A: 检查 `uvicorn` 是否正常启动，访问 `http://localhost:8000/health` 确认服务状态。

**Q: 手写版 Thought 为空**
A: 正常现象。qwen-max 在部分中间步骤会省略 Thought 直接输出 Action，解析器容忍此情况，不影响工具执行。

**Q: 想用 DeepSeek-V3**
A: 修改环境变量：
```bash
export DASHSCOPE_API_KEY="sk-xxx"   # DashScope key 同样可用于 DeepSeek
export AGENT_MODEL="deepseek-v3"
```
或者改用 DeepSeek 官方接口，修改相关文件中的 `base_url`：
```python
base_url="https://api.deepseek.com/v1"
```

**Q: 如何使用多轮对话？**
A: 在调用 API 时传入 `conversation_history` 参数，格式为 `[{"question": "...", "answer": "..."}, ...]`。agent.py 和 CLI 暂不支持多轮，建议通过 serve.py 或直接调用模块使用。