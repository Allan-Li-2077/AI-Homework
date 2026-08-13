# USAGE_GUIDE.md — 智能客服 Subagent 项目调用与测试指南

## 1. 环境准备

### 1.1 依赖安装
```bash
cd customer_service_subagents
pip install -r requirements.txt
```
> 仅 openai + fastapi + uvicorn，无 SDK。客服工具（订单/退款/物流/FAQ）用 mock 数据手写，ReAct/拓扑全手写。

### 1.2 API Key
```bash
# Windows PowerShell
$env:DEEPSEEK_API_KEY="sk-xxx"
# Linux/macOS
export DEEPSEEK_API_KEY="sk-xxx"
```
> 仅需 DeepSeek key（LLM 推理）。无需 Tavily，客服工具是本地 mock 数据。

## 2. 各步骤流程

### Step 1：CLI 跑一次客服会话
```bash
python src/agents.py
```
内置自测：跑一个多任务客服问题（查物流 + 退款 + 政策），打印主客服动作序列 + 子客服数 + 并行统计。

或直接调 `run_customer_service`：
```python
import sys; sys.path.insert(0, "src")
from agents import run_customer_service
q = "查订单 A100002 物流，给 A100003 申请退款，问下退货政策"
r = run_customer_service(q)
print(r["final_answer"])
print("并行:", r["parallel_stats"])
```

### Step 2：HTTP 服务 + 可视化
```bash
uvicorn src.serve:app --host 0.0.0.0 --port 8003
# 浏览器开 http://localhost:8003
```
- `GET /health` → LLM key 就绪状态
- `POST /query {question}` → SSE 流，逐事件推：
  `start` → `main_step` → `dispatch`(拓扑加节点) → `subagent_step` → `subagent_done` → `final`(答复+统计) → `done`
- Web 页：左侧拓扑（节点随派发动态出现、实时脉冲、完成变绿），右侧点节点看其 ReAct 过程，下方客服答复。

### Step 3：Parallel vs Serial 对比
```bash
python src/eval_compare.py --limit 4
```
4 题，每题 parallel(ThreadPool) vs serial(for 循环) 各跑一次，输出墙钟/加速对比表 + `outputs/eval_compare.json`。

## 3. 作为模块调用
```python
import sys; sys.path.insert(0, "src")
from agents import run_customer_service

# 带 trace 回调（接 SSE / 日志 / 可视化）
def on_main(step): print(f"[main] {step['action']}")
def on_sub(sid, step): print(f"[{sid}] {step['action']}")
def on_dispatch(info): print(f"派发: {info['subtopics']}")
def on_done(sid, dur, topic): print(f"[{sid}] done {dur}s")

r = run_customer_service("查 A100002 物流，A100003 退款，退货政策",
    on_main_step=on_main, on_subagent_step=on_sub,
    on_subagent_done=on_done, on_dispatch=on_dispatch)

# 单独用 ReAct loop + 自定义工具
from react_loop import ReActLoop
from customer_tools import query_order
loop = ReActLoop("my", tools={"query_order": (query_order, "查询订单")},
    max_steps=4)
print(loop.run("查 A100001")["final_answer"])
```

## 4. 可试的客服问题示例

| 问题 | 主 agent 行为 | 子客服 |
|------|--------------|--------|
| 查 A100002 物流，A100003 退款，退货政策 | dispatch 3 个 | order + after_sale + faq |
| 查 A100001 状态，问保修期，问发票怎么开 | dispatch 3 个 | order + faq + faq |
| A100004 没发货吗？配送范围？A100005 为什么退款了 | dispatch 3 个 | order + faq + order |
| 退货政策是什么 | direct_handle | 无派发 |

## 5. 调试与常见问题

**Q: 主客服不派发，自己处理多任务？**
A: `MAIN_SYSTEM` + worked example 已引导。若仍偶发，确认 `system_prompt=MAIN_SYSTEM` 传给了主 agent 的 ReActLoop。

**Q: 主 agent 卡在空 action？**
A: `_parse` 已兜底（无 Action 有文本 → 当 Final Answer）。若仍出现，检查 LLM 输出是否被 `stop=["Observation:"]` 误截。

**Q: 子客服工单/退款工单号怎么生成？**
A: `apply_refund` / `escalate_human` 用 `hashlib.md5` 生成 6 位工单号，每次调用唯一。

**Q: dispatch observation 过长？**
A: 每个子结果截短到 500 字喂回主 agent（完整 trace 仍在 shared_state 供 viz）。

**Q: 想看某子客服 ReAct 全过程？**
A: Web 页左侧点该节点，右侧切换显示其全部 Thought/Action/Observation 步骤。或读 `r["subagents"][sid]["trace"]`。

**Q: 想加新专长（如投诉处理）？**
A: 在 `customer_tools.py` 加工具 + 在 `SUBAGENT_TOOLSETS` 注册 + 在 `agents.py` 的 `ROLE_DESC` 加中文描述。
