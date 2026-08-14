# 图编排 Supervisor —— 确定性路由的 subagent 并行系统

Week15 作业：「自己实现一个可以下发 subagent 的 agent，并行完成多项工作」。
对应课程 PPT Part 6 · Graph Engineering（P19-P21），落地 **Orchestrator-Workers + Diamond fan-out/fan-in** 拓扑。

核心一句话：**主 agent（Supervisor）用确定性 Python 规则路由（代码定边），把复合任务拆给多个异构 worker（研究员/分析师/写手）并行执行（模型定节点内），再 fan-in 聚合成单一交付物。**

```
用户问题
   ↓
router.py 确定性路由（纯 Python 规则，LLM 零参与）
   ├─ 问候语     → 零派发，静态回复（确定性审批门）
   ├─ 单一任务   → 派 1 个对应 worker
   └─ 复合任务   → 两阶段 DAG：stage1 并行 fan-out ──┐
                   （研究员[联网/知识] + 分析师[计算器]）├─ 墙钟 ≈ max
                                   stage2 写手 fan-in ←┘
                                   聚合 → 单一成品交付
```

## 快速开始

```bash
pip install -r requirements.txt
export DEEPSEEK_API_KEY="sk-xxx"      # 必填：LLM 推理
export TAVILY_API_KEY="tvly-xxx"      # 可选：未设置时研究员自动降级为知识模式

# 1) CLI 演示（主演示：调研+计算+写推文）
python src/cli.py
python src/cli.py --demo single      # 单 worker 路由
python src/cli.py --demo direct      # 零派发审批门
python src/cli.py --demo chain       # 纯依赖链（并行收益≈1 的反例）
python src/cli.py --serial           # 串行对照（并行收益基线）
python src/cli.py --save-trace       # 落盘 outputs/trace_<graph_id>.json

# 2) Web 可视化（左拓扑右过程流）
uvicorn src.serve:app --host 0.0.0.0 --port 8003
# 浏览器开 http://localhost:8003

# 3) 并行 vs 串行 A/B
python src/eval_compare.py           # 3 题，每题 parallel + serial 各一次
python src/eval_compare.py --limit 1 # 快速版
```

## 目录结构

```
src/
├── router.py         # 确定性路由（核心教学：代码定边，可离线单测）
├── workers.py        # 异构 worker 注册表 + ast 安全计算器 + Tavily 降级
├── executor.py       # 节点执行器：ReAct / 单次调用双模式 + ThreadPool 并行
├── graph.py          # Supervisor 编排：route → 分阶段 fan-out → fan-in 聚合
├── react_loop.py     # 通用 ReAct 引擎（从旧项目复用，格式契约归引擎统一追加）
├── llm_client.py     # 极简 DeepSeek 客户端
├── tavily_search.py  # Tavily 搜索（urllib 零依赖，可选）
├── cli.py            # CLI 演示入口
├── serve.py          # FastAPI + SSE（端口 8003）
└── eval_compare.py   # parallel vs serial A/B
static/
├── index.html        # 左拓扑右过程流
└── viz/topology.js   # SVG 拓扑：plan 事件预画整张 DAG
outputs/              # eval_compare.json、trace_<graph_id>.json（运行生成）
作业说明.md            # 对照教程 P19/P20/P21 的完整说明
```

## 与教程要点的对应

| 教程要点（PPT Part 6） | 本项目落地 |
|----------------------|-----------|
| P20 代码定边、模型定节点内 | `router.py` 纯 Python 规则定拓扑，LLM 只在节点内干活 |
| P20 三种拓扑 | Orchestrator-Workers + Diamond fan-out/fan-in + 依赖边（Pipeline 元素） |
| P21 Schema-first 交接 | TaskPlan / NodeResult 结构化 dict 契约 |
| P21 模型分层 | 调研/计算 0.0 温度 + ReAct；写手 0.7 温度 + 单次调用；路由零 LLM 成本 |
| P21 节点级可观测 | 所有事件带 graph_id，节点事件带 node_id，全量 trace |
| P21 状态可恢复 | --save-trace 落盘完整 trace JSON，可回放 |
| P21 并行收益 + Amdahl | 分阶段 wall_clock vs serial_sum 双口径量化，含 ≈1 反例题 |

详见 `作业说明.md`。
