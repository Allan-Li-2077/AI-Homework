# 🔍 代码审查 Subagent 并行审查系统

> 基于 ReAct + Orchestrator-Workers 的智能代码审查系统，主 agent 派发 5 个维度子审查员并行分析代码。

## 🎯 应用场景

提交一个代码审查请求 → 主审查 agent 自主决策 → 派发多个维度审查员**并行**审查 → 聚合为结构化审查报告。

**核心价值**：5 个维度（安全/性能/风格/逻辑/架构）并行审查，墙钟时间 ≈ max(单个维度)，而非 sum。

## 🚀 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 设置 API Key
export DEEPSEEK_API_KEY="your-key"
# 或使用 Claude:
export ANTHROPIC_API_KEY="your-key"

# 3. 启动服务
uvicorn src.serve:app --host 0.0.0.0 --port 8003

# 4. 浏览器打开
open http://localhost:8003
```

审查其他项目：
```bash
PROJECT_ROOT=/path/to/your/project uvicorn src.serve:app --port 8003
```

## 📖 使用方式

### Web UI（推荐）
1. 浏览器打开 `http://localhost:8003`
2. 输入审查需求（或使用预设模板）
3. 点击「开始审查」
4. 实时看到：左侧拓扑图 + 右侧各审查员的 ReAct 过程
5. 审查完成后自动显示结构化报告

### 命令行
```bash
# 审查当前项目
python src/agents.py

# A/B 对比（并行 vs 串行）
python src/eval_compare.py --limit 2
```

### API
```bash
curl -X POST http://localhost:8003/review \
  -H "Content-Type: application/json" \
  -d '{"question": "审查安全性：检查安全漏洞和密钥泄露"}'
```

## 🏗 架构

```
用户审查请求
     ↓
主审查 agent (ReAct)
  ├─ read_file / search_code / list_files (单文件快速检查)
  └─ dispatch_reviewers("all") (全项目深度审查)
         ↓
   ┌──────┼──────┬──────┬──────┐ (并行)
 安全   性能   风格   逻辑   架构
审查员 审查员 审查员 审查员 审查员
 (ReAct) (ReAct) (ReAct) (ReAct) (ReAct)
   └──────┼──────┴──────┴──────┘
         ↓ 汇总（含并行加速统计）
   结构化审查报告
```

## 📊 审查维度

| 维度 | 审查重点 | 严重级别 |
|------|---------|---------|
| 🔒 安全 | 注入漏洞、密钥泄露、XSS、路径遍历 | 🔴 高危 |
| ⚡ 性能 | N+1 查询、嵌套循环、内存、阻塞 I/O | 🟡 中危 |
| ✨ 风格 | 命名、函数长度、注释、DRY、嵌套深度 | 🟢 低危 |
| 🐛 逻辑 | 空值、异常处理、资源泄漏、边界条件 | 🟡 中危 |
| 🏛 架构 | 模块耦合、循环依赖、SOLID | 💡 建议 |

## 🧪 并行优势（A/B 对比）

```bash
python src/eval_compare.py
```

预期结果：5 维度审查，并行 ≈ 60s，串行 ≈ 180s，加速比 ≈ 3.0×

并行把 N 个独立审查的墙钟从 sum（串行相加）压到 ≈max（最慢的那个）。

## 📁 项目结构

```
code_review_subagents/
├── src/
│   ├── file_tools.py      # 文件分析工具（替代 tavily_search）
│   ├── react_loop.py      # 通用 ReAct 引擎（主/子共用）
│   ├── agents.py          # 主 agent + dispatch_reviewers
│   ├── serve.py           # FastAPI + SSE 流式
│   ├── llm_client.py      # LLM 客户端
│   └── eval_compare.py    # Parallel vs Serial A/B
├── static/
│   └── index.html         # 审查可视化 UI
├── ARCHITECTURE.md        # 详细架构文档
└── requirements.txt
```

## 🔄 与市场调研 Subagent 系统的关系

本项目是市场调研 subagent 系统（`market_research_subagents/`）的**姐妹项目**，展示同一架构在不同领域的应用：

- **相同**：ReAct 引擎 + Orchestrator-Workers 拓扑 + ThreadPool 并行 + SSE 流式 + 前端拓扑可视化
- **不同**：工具从「联网搜索」变为「文件分析」，子任务从「市场侧面」变为「审查维度」

详见 [ARCHITECTURE.md](./ARCHITECTURE.md) 第 4 节的详细对比表。
