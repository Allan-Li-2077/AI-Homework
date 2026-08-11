# USAGE_GUIDE.md — AI Agent 框架对比 使用指南

## 1. 环境准备

```bash
cd agent_framework_comparison
pip install -r requirements.txt
```

环境变量：
```bash
export DEEPSEEK_API_KEY="sk-xxx"
export TAVILY_API_KEY="tvly-xxx"
```

## 2. 各步骤流程

### Step 1：CLI 跑一次
```bash
python src/agents.py
```
内置自测："多Agent系统框架选型：LangGraph vs AutoGen vs CrewAI vs Dify"

### Step 2：HTTP 服务 + 可视化
```bash
uvicorn src.serve:app --host 0.0.0.0 --port 8004
# 浏览器开 http://localhost:8004
```

### Step 3：Parallel vs Serial 对比
```bash
python src/eval_compare.py --limit 2
```

## 3. 作为模块调用
```python
import sys; sys.path.insert(0, "src")
from agents import run_research
r = run_research("多Agent系统框架选型：LangGraph vs AutoGen vs CrewAI vs Dify")
print(r["final_answer"])
print("并行:", r["parallel_stats"])
```

## 4. 示例问题
- "多Agent系统框架选型：LangGraph vs AutoGen vs CrewAI vs Dify vs 手写方案"
- "单Agent开发框架对比：LangChain vs LlamaIndex vs Semantic Kernel vs Haystack"
- "LLM应用部署平台选型：Dify vs FastGPT vs Flowise vs LangSmith"
- "RAG框架选型：LlamaIndex vs LangChain vs Haystack vs RAGFlow vs Dify知识库"
- "LangGraph 是什么"（单框架，不派发）
