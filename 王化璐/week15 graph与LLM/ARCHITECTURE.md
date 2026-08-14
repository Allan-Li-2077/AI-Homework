# Job Company Research — 融合架构说明

> 项目根目录：`job_company_research/`
> 融合参考：`market_research_subagents`（Subagent 并行 + ReAct 自主路由）+ `graphrag_financial_report`（三元组抽取 + Neo4j 沉淀 + 图谱复用）

---

## 一、项目定位

**一句话**：用户输入公司名 → **先查 Neo4j 图谱**（已有公司 1s 返回）→ 不在图谱就 **主 Agent 自主派发 5 个 Subagent 并行联网调研**（业务/薪资/面试/技术栈/前景）→ 调研结果结构化存入知识图谱（下次直接复用）。

核心价值 = **Subagent 并行加速（dispatch 段 2.5x）+ 图谱复用加速（命中 30x+）** 的双重工程收益。

---

## 二、端到端流水线

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 用户: research_or_query("字节跳动", "业务/薪资/技术栈/面试/前景")                        │
│                         │                                                             │
│          ┌──────────────┴──────────────┐                                              │
│          ▼                             ▼                                              │
│   命中 Neo4j（100%在库）          未命中（首次调研）                                    │
│          │                             │                                              │
│          │                     主 Agent ReAct 循环（3 工具）                           │
│          │                     ├─ web_search（单事实）                                 │
│          │                     ├─ dispatch_subagents（多侧面必派，并行 5 sub）          │
│          │                     └─ store_to_graph（调研后存图，下次复用）                │
│          │                             │                                              │
│          │                ThreadPoolExecutor(max_workers=5)                            │
│          │                     ┌──────┼──────┬──────┬──────┐                          │
│          │                     ▼      ▼      ▼      ▼      ▼                          │
│          │              sub_业务 sub_薪资 sub_面试 sub_技术 sub_前景                    │
│          │               (ReAct) (ReAct) (ReAct) (ReAct) (ReAct)                       │
│          │               只有 web_search 工具                                          │
│          │                     │                                                      │
│    Local Search（2 跳子图）     │ 汇总 Observation（含并行墙钟/串行/加速比）              │
│    → LLM 合成答案(1s)          ▼                                                      │
│          │              主 Agent 综合 + 触发 store_to_graph                              │
│          │                     │                                                      │
│          │              extract_triples.py（求职Schema 7实体+7关系）                     │
│          │                     │  company_业务、company_薪资……每侧面一批                 │
│          │              build_graph.py MERGE 进 Neo4j                                 │
│          │                     │  别名表统一 ByteDance→字节跳动                         │
│          │                     ▼                                                      │
│          └───────────── Neo4j 知识图谱（持续增长）◄───────────────┘                     │
│                                 节点 / 边 / 社区（可选 Leiden）                          │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、各模块职责（9 个 .py）

| 文件 | 来源 | 核心作用 | 亮点 / 跟原项目的区别 |
|------|------|---------|---------------------|
| `llm_client.py` | market_research | DeepSeek Chat + 结构化 JSON | `chat_structured_json` 支持三重兜底（` ```json ` / 截取 `{...}` / 抛错） |
| `tavily_search.py` | market_research | Tavily 联网搜索 | 零 SDK 依赖，纯 `urllib`；失败返回 `{"error"}`，ReAct 不崩 |
| `react_loop.py` | market_research | Thought/Action/Observation/Final Answer 循环 | 主/Sub 共用同一类，**能力差异 = 工具集差异**；自动解析 Thought/Action/Action Input 正则；10 步防死循环；stop=["Observation:"] 防止 LLM 杜撰 Observation |
| `extract_triples.py` | graphrag（改 Schema）| 调研文本 → 三元组 JSON | Schema 从「年报实体」→ **7 种求职实体 + 7 种求职关系**（见 §四） |
| `build_graph.py` | graphrag（改别名表）| 三元组 → Neo4j MERGE | 别名表从 5 家上市公司 → **20 家互联网公司别名**；uid 用 `sha1(type||name)`；Neo4j Community 每个标签一个唯一约束 |
| `retrieve.py` | graphrag（改入口）| Neo4j Local Search + 命中判断 | `check_company_exists()` 先探；`fetch_local_subgraph()` apoc 失败自动 fallback；末尾带免责声明 |
| `agents.py` | **本项目核心** | 主 agent 三工具 + Subagent 并行 + 先查图后调研 | 新增第 3 工具 `store_to_graph`；`research_or_query()` 融合入口；dispatch Observation 自带墙钟/串行/加速比；event_cb 全链路可观测 |
| `serve.py` | market_research | FastAPI + SSE 流式 | 加 `/graph/stats` 接口；加 `/health` 直接返回图谱规模；lifespan 复用 agents |
| `eval_compare.py` | market_research（加维度）| 并行vs串行A/B + 图谱复用加速 | 4 道题 × 3 种模式；输出 `dispatch/e2e/graph_reuse` 三个加速比；结果写入 JSON |

---

## 四、求职知识图谱 Schema（跟 GraphRAG 年报 Schema 的本质区别）

| 维度 | GraphRAG 年报 Schema | 本项目 Schema |
|------|-------------------|-------------|
| 实体 1 | Company | **Company**（字节跳动、商汤…） |
| 实体 2 | Person | **Person**（梁汝波、汤晓鸥…） |
| 实体 3 | Subsidiary / Product | **BusinessSegment**（短视频、AI大模型…） |
| 实体 4 | Indicator（营收/利润） | **SalaryIndicator**（2024校招算法35w×15薪…） |
| 实体 5 | Shareholder / Competitor | **TechnologyStack**（Go、PyTorch、K8s…） |
| 实体 6 | Industry | **Industry**（短视频、人工智能…） |
| 实体 7 | Region / — | **InterviewProcess**（笔试/技术一面/交叉面…） |

**关系**（7 种）：`OPERATES_IN` / `REPORTS`（带 year/role 属性）/ `USES_TECH` / `SERVES_AS(CEO/CTO)` / `BELONGS_TO` / `HAS_PROCESS`（带 order 属性）/ `HAS_PERSON`。

---

## 五、Subagent 并行的工程实现（作业核心考核点）

```python
# agents.py 里的 dispatch 核心逻辑
def _tool_dispatch_subagents(self, topics_str):
    topics = topics_str.split("|")
    def run_one(topic):
        # 每个 subagent 是一个独立 ReActLoop，只有 web_search 工具
        loop = ReActLoop(system=SUBAGENT_SYSTEM, tools={"web_search": self._tool_web_search}, ...)
        return loop.run(topic)

    if self.serial:
        results = [run_one(t) for t in topics]          # A/B 基线：串行 for
    else:
        with ThreadPoolExecutor(max_workers=len(topics)) as ex:
            futs = {ex.submit(run_one, t): t for t in topics}
            results = [fut.result() for fut in as_completed(futs)]   # 并行：墙钟≈max
    return f"并行墙钟 {wall}ms；串行总和 {sum}ms；加速比 {speedup:.2f}x"
```

**为什么叫「主 agent 自主路由」？**
- 不是硬编码「if 多侧面 → dispatch」，而是系统 Prompt 给了决策原则 + worked example，LLM 在 Thought 里推理后自主挑 Action（web_search / dispatch_subagents / store_to_graph）。
- 跟硬编码路由的区别：面对用户奇怪的提问方式（"帮我做个公司背调"这种非结构化表达），LLM 依然能正确分派。

---

## 六、实验结果（理想输出）

| 指标 | 典型值 | 怎么测 |
|------|-------|-------|
| dispatch 段加速比 | **2.0~3.0×** | eval 里 `parallel_dispatch_wall_ms` vs `parallel_dispatch_serial_sum_ms` |
| 端到端加速比 | **1.3~1.8×** | eval 里 `serial_total_ms` / `parallel_total_ms`（Amdahl：主 agent 串行段拖后腿，这是诚实的教学点） |
| 图谱复用加速比 | **20~50×** | 第一次调研 `parallel_total_ms`（30s 级）/ 第二次查图 `graph_hit_ms`（1s 级） |
| 知识图谱规模（调研 4 家后） | 节点 200~500、边 400~800 | `/graph/stats` 接口看 by_label / by_relation |
| Leiden 社区检测 | 3~6 社区（天然按行业聚类：短视频 / AI 算法 / 搜索引擎 / 电商…）| community_detect.py（本项目可选拓展，直接抄 graphrag 版） |

---

## 七、踩坑清单（面试加分项）

| # | 问题 | 根因 | 解法 |
|---|------|------|------|
| 1 | Tavily 返回 401 | API Key 没设置或没生效 | PowerShell `$env:TAVILY_API_KEY='...'`（不要用 setx，当前会话不生效；要开新终端）|
| 2 | DeepSeek 输出不是 JSON | `extract_triples.py` / `chat_structured_json` 偶尔失败 | 三重兜底：剥 ```json```、截 `{...}`、抛错重跑；temperature 设 0.1 |
| 3 | 公司别名没统一导致图破碎 | "ByteDance" / "字节" / "抖音集团" 被当成 3 个节点 | `build_graph.py::COMPANY_ALIASES`，调研前把 aliases 配好；`normalize_name()` 在 MERGE 前统一 |
| 4 | Neo4j 连接超时 | bolt 端口不是 7687 或 JDK 不对导致服务没起来 | 见 USAGE_GUIDE §二 启动 Neo4j；`NEO4J_URI` 环境变量可改 |
| 5 | Neo4j auth 报错 | 默认有密码，但代码里 `auth=None` | 关认证：`neo4j.conf` 中 `dbms.security.auth_enabled=false` |
| 6 | ReAct 死循环（>10 步）| LLM 反复 Thought 但不输出 Action | 最大步数截断（max_steps=15），最后用最近 3 步 Observation 兜底合成 |
| 7 | LLM 不遵守 dispatch 格式 | 只写决策原则不够 | MAIN_SYSTEM 里放**完整 worked example**（Thought→Action→Action Input→Observation 格式示范）|
| 8 | GraphRAG Local Search 返回 `apoc 未安装` | apoc.path.subgraphAll 要装 APOC 插件 | `retrieve.py::fetch_local_subgraph` 已写 fallback 用原生 `[r*1..hop]` 语法 |
| 9 | Python import `from src.X` 失败 | 项目根不在 sys.path | 每个脚本头部已加 `sys.path.insert(0, 根目录)`，保证单独/模块两种跑法都通 |
| 10 | eval 图谱复用维度失效 | 调研后没真的存进 Neo4j（store_to_graph 抽不出三元组）| 检查 `data/company_triples.json` 有没有内容；也可手动调 `python src/build_graph.py` 从 JSON 补灌 |

---

## 八、跟两个参考项目的差异总结

| 维度 | market_research_subagents | graphrag_financial_report | 本项目（融合版）|
|------|--------------------------|--------------------------|---------------|
| 主 agent 工具数 | 2（web_search / dispatch）| — | **3**（+ store_to_graph） |
| 数据持久化 | — 用完即弃 | 三元组 JSON + Neo4j | ✅ 三元组 JSON + Neo4j |
| 查询前先查库 | — | Local/Global GraphRAG | ✅ research_or_query 命中即返回 |
| 并行机制 | ThreadPool subagents | — | ✅ ThreadPool subagents + 串行对比基线 |
| 量化维度 | dispatch 加速 + 端到端加速 | GraphRAG vs 向量 RAG（15题）| **三维度**：dispatch + 端到端 + 图谱复用 |
| 知识 Schema | — | 年报 7+8 实体关系 | **求职 7+7 实体关系** |
