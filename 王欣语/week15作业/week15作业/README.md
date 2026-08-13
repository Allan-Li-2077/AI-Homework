# Subagent 并行调研系统

## 核心设计

- **主 Agent**：ReAct 循环，有 2 个工具：
  - `web_search`：单次联网搜索（简单问题直接用）
  - `dispatch_subagents`：派发多个 subagent 并行调研（多侧面问题用）
  
- **Subagent**：也是 ReAct 循环，只有 `web_search` 工具
  
- **并行执行**：使用 `ThreadPoolExecutor` 并行跑 N 个 subagent
  - wall-clock ≈ max(单agent时长)，而非 sum

## 文件结构

```
week15作业/
├── llm_client.py      # 极简 DeepSeek LLM 客户端
├── tavily_search.py   # Tavily 联网搜索（urllib 零依赖）
├── react_loop.py      # 通用 ReAct 引擎（主/subagent 共用）
├── agents.py          # 主 agent + dispatch_subagents 并行派发
├── serve.py           # FastAPI + SSE 流式服务 + Web 页面
├── requirements.txt   # 依赖
└── README.md          # 本文件
```

## 快速开始

### 1. 安装依赖

```bash
cd week15作业
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
export DEEPSEEK_API_KEY="sk-xxx"     # DeepSeek API Key
export TAVILY_API_KEY="tvly-xxx"     # Tavily API Key
```

### 3. CLI 运行

```bash
python agents.py
```

### 4. 启动 Web 服务

```bash
python serve.py
# 或
uvicorn serve:app --host 0.0.0.0 --port 8002
```

浏览器访问 http://localhost:8002

## 架构说明

```
用户问题
   ↓
主 agent ReAct 循环（工具: web_search + dispatch_subagents）
   ├─ 简单事实 → 直接 web_search → Final Answer
   └─ 多侧面调研 → dispatch_subagents("课题1|课题2|课题3")
                       ↓
              ┌─ subagent1 ReAct(web_search) ─┐
              ├─ subagent2 ReAct(web_search) ─┤ 并行(ThreadPool)
              └─ subagent3 ReAct(web_search) ─┘
                       ↓ 汇总（含并行加速统计）
              主 agent 综合成报告 → Final Answer
```

## 教学要点

1. **动态 Orchestrator-Workers**：主 agent 自主决定派几个 subagent，非固定拓扑
2. **并行优势量化**：对比 wall_clock（并行）vs serial_sum（串行）
3. **ReAct 通用引擎**：主/subagent 共用同一套 ReActLoop，区别只在 tools
