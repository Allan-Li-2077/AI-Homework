# 通用多 Agent 问答系统（general_multi_agent）

**1 个主 agent + 多个专业子 agent，全员 ReAct 架构、全员联网搜索**。

## 架构

```
用户问题
   ↓
主 agent ReAct 循环（工具: web_search + dispatch_subagents）
   ├─ 单一事实 → 直接 web_search → Final Answer
   └─ 多侧面问题 → dispatch_subagents("角色:子课题 | 角色:子课题")
                       ↓
              ┌─ finance 财经分析师 ─┐
              ├─ tech 科技专家      ─┤ 并行（ThreadPoolExecutor）
              ├─ news 新闻记者      ─┤
              └─ general 综合研究员 ─┘
                       ↓ 汇总（含并行加速统计）
              主 agent 综合成报告 → Final Answer
```

- **主 agent**：ReAct 循环，`web_search` + `dispatch_subagents` 两个工具，根据问题自主路由
- **子 agent 池**：finance / tech / news / general 四个角色，全部 `ReActLoop` + `web_search`
- **ReAct 输出协议**：JSON 结构化（`{"thought", "action", "action_input"}` 或 `{"thought", "final_answer"}`），`json_mode=True` 强制合法 JSON
- **联网**：博查 Bocha Web Search API（requests，`BOCHA_API_KEY`）
- **LLM**：DeepSeek deepseek-chat（OpenAI 兼容接口，`DEEPSEEK_API_KEY`）

## 使用

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 API Key（写入 ~/.zshrc 避免每次 export）
export DEEPSEEK_API_KEY="sk-xxx"
export BOCHA_API_KEY="sk-xxx"   # https://open.bochaai.com 注册免费领取

# 交互式问答（并行派发，默认）
python src/cli.py

# 直接传问题
python src/cli.py "分析2025年中国AI行业：市场规模、技术趋势、主要公司"

# 子 agent 串行执行（对比并行加速基线）
python src/cli.py --serial "分析2025年中国AI行业"
```

## 模块结构

| 文件 | 职责 |
|------|------|
| `src/llm_client.py` | DeepSeek 客户端，`llm_chat(json_mode=True)` 支持 JSON 结构化输出 |
| `src/bocha_search.py` | 博查联网搜索（requests），失败返回 `{error}` 不抛异常 |
| `src/react_loop.py` | 通用 ReAct 引擎（主/子共用），JSON 解析 + 正则兜底链 |
| `src/dispatcher.py` | 派发引擎（独立模块）：解析"角色:子课题"、并行执行、汇总、parallel_stats |
| `src/agents.py` | 角色池 + MAIN_SYSTEM + 主 agent 组装 |
| `src/cli.py` | 交互式 CLI 入口 |

## 关键设计

- **派发逻辑独立**：`DispatchEngine` 不依赖 agents.py，角色池作为参数传入，可复用到任何主 agent
- **全员联网**：主 agent 和每个子 agent 都有 `web_search` 工具
- **JSON 输出协议**：json.loads 零歧义解析；`_parse` 保留正则兜底 + "有文本当 Final Answer" 防死循环
- **并行量化**：`parallel_stats` 记录 wall_clock vs serial_sum（真实跑出 2.34× 加速）
- **context 保护**：子结果截短 500 字喂回主 agent
