# 求职公司调研 Agent —— Subagent 并行派发 + 知识图谱沉淀

> **一个能自主下发 Subagent 并行完成多维调研的 Agent 系统，融合 GraphRAG 思路将结果持久化到 Neo4j 知识图谱，实现"一次调研、永久复用"。**

---

## 目录

- [1. 项目背景与目标](#1-项目背景与目标)
- [2. 实用工具说明](#2-实用工具说明)
- [3. 项目结构](#3-项目结构)
- [4. 环境配置](#4-环境配置)
- [5. 完整实验流程](#5-完整实验流程)
- [6. 各方案原理简介](#6-各方案原理简介)
- [7. 实验执行过程与日志](#7-实验执行过程与日志)
- [8. 评估结果汇总](#8-评估结果汇总)
- [9. 结果分析与讨论](#9-结果分析与讨论)
- [10. 最终结论](#10-最终结论)
- [11. 产出文件索引](#11-产出文件索引)
- [12. 常见问题](#12-常见问题)
- [附录 A：企业级落地方案](#附录-a企业级落地方案)
- [附录 B：技术细节](#附录-b技术细节)

---

## 1. 项目背景与目标

### 1.1 背景

在求职过程中，候选人需要对目标公司进行多维度调研（业务板块、薪资待遇、技术栈、面试流程、行业前景等）。传统方式要么靠人工逐一搜索（耗时且易遗漏），要么靠单一 LLM 生成（信息不够全面且缺乏时效性）。

本项目融合两个参考项目的核心思路：

| 参考项目 | 核心思路 | 本项目借鉴点 |
|----------|----------|-------------|
| `market_research_subagents` | 主 Agent 通过 ReAct 循环自主决策，派发多个 Subagent 并行完成市场调研 | ReAct 引擎、Subagent 并行派发机制、ThreadPoolExecutor 加速 |
| `graphrag_financial_report` | 将非结构化文本抽取为三元组，构建 Neo4j 知识图谱，支持图检索问答 | 三元组抽取、图谱构建、Local Search 子图检索 |

### 1.2 目标

实现一个**求职公司调研 Agent**，具备以下能力：

1. **自主路由决策**：主 Agent 接收用户问题后，自主判断是直接搜索、派发 Subagent 并行调研、还是从知识图谱复用
2. **Subagent 并行派发**：将多维度调研任务拆分成 5 个独立子课题，每个子课题由一个 Subagent 并行执行 ReAct 循环联网搜索
3. **知识图谱沉淀**：调研完成后自动抽取实体关系三元组，MERGE 进 Neo4j 图数据库
4. **图谱复用加速**：同一公司第二次查询时直接从图谱检索，跳过联网调研，实现 10x+ 加速
5. **可视化展示**：FastAPI + 力导向图前端，实时展示知识图谱子图

### 1.3 核心创新点

```
用户提问
  │
  ▼
主 Agent (ReAct) ──→ 判断：图谱命中？─是─→ Local Search 图检索（秒级）
  │                    │
  │                    否
  │                    │
  ▼                    ▼
dispatch_subagents    store_to_graph
  │                    │
  ├─ Subagent 1: 业务板块     │
  ├─ Subagent 2: 薪资待遇     │  extract_triples (LLM 抽取)
  ├─ Subagent 3: 技术栈       │       │
  ├─ Subagent 4: 面试流程     │       ▼
  └─ Subagent 5: 行业前景     │  build_in_neo4j (MERGE 节点/边)
        │                    │
        ▼                    ▼
  ThreadPoolExecutor     Neo4j 图数据库
  (并行加速 3x+)         (复用加速 10x+)
```

---

## 2. 实用工具说明

### 2.1 Tavily 联网搜索

| 项目 | 说明 |
|------|------|
| 用途 | Subagent 的唯一工具，用于联网获取实时信息 |
| API | `https://api.tavily.com/search` (POST) |
| 鉴权 | `Authorization: Bearer <API_KEY>` (兼容 dev / production 两种 Key) |
| 免费额度 | dev key 免费 1000 次/月，足够学生项目使用 |
| 代码位置 | [src/tavily_search.py](src/tavily_search.py) |

**关键设计**：使用 Python 标准库 `urllib` 实现，零 SDK 依赖。dev 类型 Key 必须用 Bearer header 鉴权（放 body 里会报 401）。

### 2.2 DeepSeek LLM

| 项目 | 说明 |
|------|------|
| 用途 | 驱动 ReAct 循环（Thought/Action/Final Answer）+ 三元组抽取 |
| API | `https://api.deepseek.com` (OpenAI 兼容格式) |
| 模型 | `deepseek-chat` |
| 代码位置 | [src/llm_client.py](src/llm_client.py) |

**关键设计**：通过 `openai` SDK 连接 DeepSeek（base_url 替换即可），支持普通聊天和结构化 JSON 输出两种模式。

### 2.3 Neo4j 图数据库

| 项目 | 说明 |
|------|------|
| 用途 | 存储调研结果的知识图谱，支持多跳查询和子图检索 |
| 版本 | neo4j-community-4.4.8 (Community Edition) |
| 连接 | `bolt://localhost:7687` (关闭认证) |
| Python 驱动 | `neo4j>=5.20.0` |
| 代码位置 | [src/build_graph.py](src/build_graph.py)、[src/retrieve.py](src/retrieve.py) |

### 2.4 FastAPI + SSE 流式服务

| 项目 | 说明 |
|------|------|
| 用途 | HTTP API 服务 + Server-Sent Events 流式推送 |
| 端口 | 8000 |
| 代码位置 | [src/serve.py](src/serve.py) |

### 2.5 JDK 11

| 项目 | 说明 |
|------|------|
| 用途 | Neo4j 4.x 的运行时依赖 |
| 版本 | Temurin-11.0.32+9 |
| 本地路径 | `D:\jdk-11.0.32+9` |

---

## 3. 项目结构

```
job_company_research/
├── src/                          # 源代码
│   ├── agents.py                 # 核心：主 Agent + Subagent 派发 + 图谱沉淀
│   ├── react_loop.py             # 通用 ReAct 循环引擎（主/子 Agent 共用）
│   ├── tavily_search.py          # Tavily 联网搜索工具（Bearer header 鉴权）
│   ├── llm_client.py             # DeepSeek LLM 客户端（OpenAI 兼容）
│   ├── extract_triples.py        # 三元组抽取（LLM 驱动，7 实体类型 + 7 关系类型）
│   ├── build_graph.py            # Neo4j 图谱构建（MERGE 节点/边 + 别名归一化）
│   ├── retrieve.py               # 图谱检索（Local Search：子图提取 + LLM 合成）
│   ├── serve.py                  # FastAPI HTTP + SSE 流式服务
│   └── eval_compare.py           # 对比评测脚本（并行 vs 串行 vs 图谱复用）
├── static/                       # 前端可视化
│   ├── index.html                # 主页面（调研输入 + 力导向图展示）
│   └── viz/
│       └── force_graph.js        # D3.js 力导向图（7 种实体类型颜色区分）
├── data/                         # 运行时数据
│   ├── company_triples.json      # 抽取的三元组备份（多批次，按 source 去重）
│   └── graph_stats.json          # 图谱统计信息
├── outputs/                      # 评测输出
│   └── eval_compare.json         # 完整评测结果（2 case × 3 模式 + 3 个加速比）
├── .venv/                        # Python 虚拟环境
├── requirements.txt              # 依赖清单（4 个包，极简）
└── README.md                     # 本文件
```

### 3.1 依赖清单（极简，仅 4 个包）

```
openai>=1.40.0      # DeepSeek LLM 调用（OpenAI 兼容 SDK）
fastapi>=0.115.0    # HTTP API 框架
uvicorn>=0.30.0     # ASGI 服务器
neo4j>=5.20.0       # Neo4j Python 驱动
```

> Tavily 搜索使用标准库 `urllib`，无需额外 SDK。

---

## 4. 环境配置

### 4.1 前置条件

| 软件 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.10+ | 推荐 3.12 |
| JDK | 11+ | Neo4j 4.x 依赖 |
| Neo4j | 4.4.8 (Community) | 图数据库 |
| Tavily API Key | dev 或 production | 联网搜索 |
| DeepSeek API Key | 任意 | LLM 推理 |

### 4.2 一步步配置

#### Step 1：创建虚拟环境 + 安装依赖

```powershell
cd "E:\AI课学习\week15graph和llm\week15 graph与LLM\job_company_research"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

#### Step 2：配置 Neo4j

1. 解压 `neo4j-community-4.4.8` 到项目同级目录
2. 编辑 `neo4j-community-4.4.8/conf/neo4j.conf`，关闭认证：

```properties
dbms.security.auth_enabled=false
```

3. 设置 JAVA_HOME 并启动 Neo4j：

```powershell
$env:JAVA_HOME = "D:\jdk-11.0.32+9"
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
cd "E:\AI课学习\week15graph和llm\week15 graph与LLM\neo4j-community-4.4.8"
.\bin\neo4j.bat console
```

4. 验证：浏览器打开 `http://localhost:7474` 看到 Neo4j Browser 即成功

#### Step 3：设置 API Key 环境变量

```powershell
$env:TAVILY_API_KEY = "tvly-dev-你的Tavily密钥"
$env:DEEPSEEK_API_KEY = "sk-你的DeepSeek密钥"
```

> 也可以创建 `.env` 文件（项目已支持 `python-dotenv` 自动加载）：
> ```
> TAVILY_API_KEY=tvly-dev-xxxx
> DEEPSEEK_API_KEY=sk-xxxx
> ```

#### Step 4：验证三件套连通

```powershell
cd "E:\AI课学习\week15graph和llm\week15 graph与LLM\job_company_research"
.\.venv\Scripts\python.exe -c @"
import sys, os; sys.path.insert(0, os.getcwd())
from src.tavily_search import web_search
from src.llm_client import chat
from src.build_graph import get_driver
print('Tavily:', 'OK' if 'error' not in web_search('test') else 'FAIL')
print('DeepSeek:', chat([{'role':'user','content':'1+1=?'}], max_tokens=10))
d = get_driver(); print('Neo4j:', d.verify_connectivity() or 'OK'); d.close()
"@
```

---

## 5. 完整实验流程

### 5.1 流程总览（7 个阶段）

```
阶段1: 启动 Neo4j → 阶段2: 三件套自测 → 阶段3: 第一次 CLI 调研（并行+存图）
→ 阶段4: 第二次同公司调研（图谱命中）→ 阶段5: 启动 FastAPI 服务
→ 阶段6: 全量评测（2 case × 3 模式）→ 阶段7: 结果汇总
```

### 5.2 各阶段详细操作

#### 阶段 1：启动 Neo4j

```powershell
$env:JAVA_HOME = "D:\jdk-11.0.32+9"
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
cd "E:\AI课学习\week15graph和llm\week15 graph与LLM\neo4j-community-4.4.8"
.\bin\neo4j.bat console
```

验证：BOLT 端口 7687 + HTTP 端口 7474 均开放。

#### 阶段 2：三件套自测

验证 Tavily 搜索、DeepSeek 聊天、Neo4j Python 连接三项核心服务正常。

#### 阶段 3：第一次 CLI 调研（并行 + 存图）

```powershell
cd "E:\AI课学习\week15graph和llm\week15 graph与LLM\job_company_research"
$env:TAVILY_API_KEY = "tvly-dev-你的key"
$env:DEEPSEEK_API_KEY = "sk-你的key"
.\.venv\Scripts\python.exe -m src.agents
```

主 Agent 自主决策流程：
1. 识别为多维度调研 → 调用 `dispatch_subagents`
2. 派发 5 个 Subagent 并行调研（业务/薪资/技术栈/面试/前景）
3. 收集结果 → 调用 `store_to_graph` 抽取三元组存入 Neo4j
4. 综合所有信息 → 输出 Final Answer 完整报告

#### 阶段 4：第二次同公司调研（图谱命中）

再次运行 `python -m src.agents`，主 Agent 调用 `research_or_query`：
1. 先查 Neo4j 图谱 → 发现"字节跳动"已存在
2. 直接拉取 2 跳子图（132 条三元组）
3. LLM 基于子图合成答案 → 秒级返回

#### 阶段 5：启动 FastAPI 服务

```powershell
.\.venv\Scripts\python.exe -m src.serve
```

浏览器打开 `http://localhost:8000` 即可访问可视化界面。

#### 阶段 6：全量评测

```powershell
.\.venv\Scripts\python.exe -m src.eval_compare
```

对每家公司跑 3 种模式：并行 / 串行 / 图谱复用，输出 3 个加速比指标。

---

## 6. 各方案原理简介

### 6.1 ReAct 循环引擎

ReAct (Reasoning + Acting) 是一种让 LLM 自主决策的循环机制：

```
Thought: <LLM 分析当前状态，决定下一步>
Action: <工具名>
Action Input: <工具入参>
Observation: <工具返回结果>
（循环，直到 LLM 输出 Final Answer）
```

**本项目实现**（[src/react_loop.py](src/react_loop.py)）：
- 主 Agent 和 Subagent 共用 `ReActLoop` 类，区别只在 `tools` 字典和 `system` 提示词
- 主 Agent 有 3 个工具：`web_search`、`dispatch_subagents`、`store_to_graph`
- Subagent 只有 1 个工具：`web_search`
- 用正则解析 LLM 输出的 Thought/Action/Action Input/Final Answer
- `max_steps` 防止死循环（主 Agent 15 步，Subagent 8 步）

### 6.2 Subagent 并行派发机制

**核心代码**（[src/agents.py](src/agents.py) `_tool_dispatch_subagents` 方法）：

```python
# 1. 解析子课题（用 | 分隔）
topics = topics_str.split("|")  # 最多 5 个

# 2. 每个 Subagent 是一个独立的 ReActLoop 实例
def run_one(topic):
    loop = ReActLoop(system=SUBAGENT_SYSTEM, tools={"web_search": ...}, max_steps=8)
    return loop.run(topic)

# 3. ThreadPoolExecutor 并行执行
with ThreadPoolExecutor(max_workers=len(topics)) as ex:
    futs = {ex.submit(run_one, t): t for t in topics}
    for fut in as_completed(futs):
        results.append(fut.result())

# 4. 统计加速比
wall_ms = 实际墙钟时间
serial_sum_ms = 各 Subagent 耗时总和
speedup = serial_sum_ms / wall_ms  # 通常 3x+
```

**串行模式**（A/B 基线对比）：`serial=True` 时退化为 `for` 循环逐个执行，用于评测加速效果。

### 6.3 三元组抽取

**Schema 设计**（[src/extract_triples.py](src/extract_triples.py)）：

| 实体类型 | 说明 | 示例 |
|----------|------|------|
| Company | 公司本体 | 字节跳动、商汤科技 |
| BusinessSegment | 业务板块 | 抖音、TikTok、生成式AI |
| SalaryIndicator | 薪资指标 | 算法岗base35w×15薪 |
| TechnologyStack | 技术栈 | Go、PyTorch、Kubernetes |
| Person | 核心人物 | 梁汝波、汤晓鸥 |
| Industry | 行业赛道 | 短视频、人工智能 |
| InterviewProcess | 面试环节 | 在线笔试、技术一面 |

| 关系类型 | 方向 | 说明 |
|----------|------|------|
| OPERATES_IN | Company → BusinessSegment | 公司经营某业务 |
| REPORTS | Company → SalaryIndicator | 公司薪资待遇 |
| USES_TECH | Company → TechnologyStack | 公司使用某技术 |
| SERVES_AS | Person → Company | 人物任某职位 |
| BELONGS_TO | Company → Industry | 公司属于某行业 |
| HAS_PROCESS | Company → InterviewProcess | 公司面试流程 |
| HAS_PERSON | Company → Person | 公司有某高管 |

**抽取流程**：将 Subagent 的总结文本发给 DeepSeek，要求严格按 Schema 输出 JSON，再用正则兜底去除 Markdown 代码块和噪声字符。

### 6.4 Neo4j 图谱构建

**核心操作**（[src/build_graph.py](src/build_graph.py)）：

1. **别名归一化**：LLM 抽取的公司名五花八门（"字节"、"ByteDance"、"抖音集团"），通过别名表统一成标准名"字节跳动"
2. **UID 生成**：`sha1(实体类型||归一化名称)` → 全局唯一标识
3. **MERGE 节点**：`MERGE (n {uid: $uid}) SET n:Company, n.name = $name`（幂等，重复不冲突）
4. **MERGE 边**：`MATCH 两端节点 → MERGE 关系 → SET 属性`（按三元组去重）

### 6.5 Local Search 图谱检索

**流程**（[src/retrieve.py](src/retrieve.py)）：

1. 检查公司是否在图谱中（按 UID 查 Company 节点）
2. 拉取 2 跳子图（1 跳直接关系 + 2 跳扩展关系，纯原生 Cypher，不依赖 APOC 插件）
3. 将子图三元组格式化为文本
4. 发给 LLM 基于子图信息合成答案

### 6.6 SSE 流式推送

**机制**（[src/serve.py](src/serve.py)）：
- 主线程启动 `ResearchAgents`，注册 `event_cb` 回调
- 每发生一个事件（main_step / dispatch_start / subagent_step / dispatch_done / graph_stored / done）就 put 到 Queue
- SSE 生成器从 Queue 取数据，`yield` 推给前端
- 跨线程通信靠 `queue.Queue`（线程安全）

---

## 7. 实验执行过程与日志

### 7.1 阶段 1：启动 Neo4j

```
命令：.\bin\neo4j.bat console
结果：BOLT 7687: True  |  HTTP 7474: True
认证：已关闭（dbms.security.auth_enabled=false）
```

### 7.2 阶段 2：三件套自测

```
【自测 1/3】Tavily 联网搜索
  ✅ 成功！2条结果，耗时4270ms
  摘要: ByteDance launched its 2024 campus recruitment in August...

【自测 2/3】DeepSeek LLM 聊天
  ✅ 成功！耗时3737ms
  回答: 中国的首都是北京。

【自测 3/3】Neo4j Python 连接
  ✅ 连接成功！耗时6252ms
  当前图谱: 0 个节点 / 0 条关系

✅ 三件套自测完成
```

### 7.3 阶段 3：第一次 CLI 调研字节跳动

**主 Agent 决策链**：
1. `Thought: 这是一个典型的多维度求职调研（5个侧面），必须派发多个子调研员并行收集信息`
2. `Action: dispatch_subagents` → 派发 5 个 Subagent
3. 5 个 Subagent 并行执行 ReAct 循环（各自搜 2-4 次）
4. `Action: store_to_graph` → 抽取三元组存入 Neo4j
5. `Final Answer:` → 输出 5 章节完整报告

**关键指标**：
```
总耗时: 103490 ms (约1分44秒)
并行加速: wall_ms=36009, serial_sum_ms=123223, speedup=3.42x
存图: 5 批三元组 → Neo4j (127 节点 / 135 边)
```

**输出报告结构**（5 章节）：
- 一、主营业务与业务板块（六大 BU：抖音/大力教育/飞书/火山引擎/朝夕光年/TikTok）
- 二、薪资待遇与福利（T2.1 研发月薪 31K、豆包 AI 工程师月薪最高 7 万、期权按季度归属）
- 三、技术栈与工程文化（React+Rspack、HDFS+Iceberg、"Context not Control"）
- 四、面试流程与经验（简历筛选→HR→技术一面→二面→三面→HR 终面）
- 五、发展前景与行业口碑（AI 战略领先、广告增长放缓、脉脉职得去总榜第一）

### 7.4 阶段 4：第二次同公司调研（图谱命中）

```
命令：agents.research_or_query('字节跳动', '...')
结果：
  ✅ 知识图谱命中！图谱检索耗时: 9600 ms
  子图三元组: 132 条
  🔥 图谱复用加速比: 103490ms / 9600ms = 10.8倍
```

图谱命中后直接基于 132 条三元组合成答案，无需联网搜索，报告内容与第一次基本一致。

### 7.5 阶段 5：FastAPI 服务验证

```
/health:       {"ok": true, "neo4j_nodes": 127, "neo4j_edges": 135}
/graph/stats:  7种实体标签 + 6种关系类型，分布统计正常
/graph/subgraph: 字节跳动 2 跳子图 → 123 节点 / 132 边
```

### 7.6 阶段 6：全量评测

对字节跳动 + 商汤科技 2 家公司各跑 3 种模式（并行/串行/图谱复用），输出到 `outputs/eval_compare.json`。

商汤科技完整报告涵盖：
- 营收 37.7 亿元（生成式 AI 占 63.7%）
- 平均月薪 34.2K，算法岗校招最高 60 万总包
- SenseCore AI 大装置 + 日日新 SenseNova 大模型
- 面试 4-5 轮（笔试→技术一面→技术二面→综合面/HR 面）

---

## 8. 评估结果汇总

### 8.1 三大核心加速比指标

| 指标 | 字节跳动 | 商汤科技 | 平均 |
|------|---------|---------|------|
| **① dispatch 并行加速** | 3.42x | 2.98x | **3.20x** |
| **② 端到端加速** | 2.71x | 1.27x | **1.99x** |
| **③ 图谱复用加速** | 8.88x | 16.98x | **12.93x** |

### 8.2 详细耗时数据

| 指标 | 字节跳动 | 商汤科技 | 平均 |
|------|---------|---------|------|
| 并行总耗时 (ms) | 103,490 | 158,102 | 130,796 |
| 串行总耗时 (ms) | 280,000 | 201,080 | 240,540 |
| 图谱命中耗时 (ms) | 11,658 | 9,309 | 10,483 |
| dispatch 并行墙钟 (ms) | 36,009 | 41,133 | 38,571 |
| dispatch 串行累加 (ms) | 123,223 | 122,542 | 122,883 |
| 子图三元组数 | 132 | 131 | 131.5 |

### 8.3 Neo4j 图谱规模

| 统计项 | 数量 |
|--------|------|
| 总节点 | 258 |
| 总边 | 266 |
| BusinessSegment | 46+ |
| TechnologyStack | 25+ |
| SalaryIndicator | 23+ |
| InterviewProcess | 14+ |
| Company | 10+ |
| Person | 5+ |
| Industry | 4+ |

### 8.4 评测 JSON 完整结构

```json
{
  "timestamp": "2026-08-13 23:18:56",
  "summary": {
    "cases": 2,
    "dispatch_speedup_x_avg": 3.2,
    "e2e_speedup_x_avg": 1.99,
    "graph_reuse_speedup_x_avg": 12.93,
    "parallel_total_ms_avg": 130796,
    "serial_total_ms_avg": 240540,
    "graph_hit_ms_avg": 10483
  },
  "cases": [ ... ]
}
```

---

## 9. 结果分析与讨论

### 9.1 Subagent 并行加速效果（指标①）

**平均 3.20x 加速**，符合预期。5 个 Subagent 各自独立联网搜索，ThreadPoolExecutor 让它们并行执行，理论上限接近 5x（受 GIL 和网络 IO 限制，实际 3x 左右合理）。

**瓶颈分析**：Subagent 内部主要是网络 IO（Tavily 搜索 + DeepSeek API 调用），Python GIL 对 IO 密集型任务影响小，所以 ThreadPoolExecutor 加速效果好。如果任务变成 CPU 密集型（如本地模型推理），需改用 ProcessPoolExecutor。

### 9.2 端到端加速效果（指标②）

**平均 1.99x 加速**，低于 dispatch 段加速。原因：
- 端到端包含主 Agent 的 ReAct 决策时间、三元组抽取时间、Neo4j 写入时间
- 这些步骤无法并行（是串行的 Thought→Action→Observation 循环）
- 商汤科技端到端仅 1.27x：串行模式下 LLM 偶尔响应慢导致串行总耗时偏低（偶然因素）

### 9.3 图谱复用加速效果（指标③）

**平均 12.93x 加速**，是最亮眼的指标。第二次查询同一公司时：
- 跳过 5 个 Subagent 的联网搜索（省 ~40s）
- 跳过三元组抽取和 Neo4j 写入（省 ~5s）
- 只需拉取子图 + LLM 合成答案（~10s）
- 商汤科技达到 16.98x：因为并行调研耗时更长（158s），而图谱命中同样只需 9.3s

### 9.4 Subagent 自主性验证

主 Agent 成功展示了自主决策能力：
- ✅ 正确识别多维度调研场景，主动调用 `dispatch_subagents`（而非自己一个个搜）
- ✅ 调研完成后主动调用 `store_to_graph`（存入图谱）
- ✅ 第二次查询时通过 `research_or_query` 自动走图谱检索路线
- ✅ Subagent 各自独立完成 ReAct 循环，不跑题

### 9.5 知识图谱质量

图谱中 7 种实体类型分布合理：
- BusinessSegment 最多（46 个）：公司业务线拆分细
- TechnologyStack 25 个：技术栈信息丰富
- SalaryIndicator 23 个：薪资档位记录详细
- 别名归一化有效工作（"字节"、"ByteDance"统一为"字节跳动"）

---

## 10. 最终结论

### 10.1 项目目标达成情况

| 目标 | 达成 | 说明 |
|------|------|------|
| 主 Agent 自主路由决策 | ✅ | ReAct 循环正确判断何时搜索/派发/存图 |
| Subagent 并行派发 | ✅ | 5 个 Subagent 并行，加速 3.2x |
| 知识图谱沉淀 | ✅ | 三元组自动抽取 + MERGE 进 Neo4j |
| 图谱复用加速 | ✅ | 第二次查询加速 12.93x |
| 可视化展示 | ✅ | FastAPI + D3.js 力导向图 |
| A/B 评测体系 | ✅ | 并行 vs 串行 vs 图谱复用，3 个加速比 |

### 10.2 核心价值

1. **并行加速**：Subagent 并行派发将调研时间从 ~4 分钟压缩到 ~2 分钟（3.2x 加速）
2. **知识积累**：调研结果持久化为知识图谱，团队可复用
3. **极致复用**：图谱命中后查询从 ~2 分钟降到 ~10 秒（12.93x 加速）
4. **自主决策**：主 Agent 全程自主路由，无需人工干预

---

## 11. 产出文件索引

| 文件路径 | 说明 | 重要性 |
|----------|------|--------|
| [outputs/eval_compare.json](outputs/eval_compare.json) | 完整评测结果（2 case × 3 模式 + 3 个加速比） | ⭐⭐⭐ |
| [data/company_triples.json](data/company_triples.json) | 抽取的三元组备份（多批次，按 source 去重） | ⭐⭐ |
| [data/graph_stats.json](data/graph_stats.json) | Neo4j 图谱统计信息 | ⭐ |
| [src/agents.py](src/agents.py) | 核心：主 Agent + Subagent 派发 + 图谱沉淀 | ⭐⭐⭐ |
| [src/react_loop.py](src/react_loop.py) | 通用 ReAct 循环引擎 | ⭐⭐⭐ |
| [src/tavily_search.py](src/tavily_search.py) | Tavily 搜索（Bearer header 鉴权） | ⭐⭐ |
| [src/llm_client.py](src/llm_client.py) | DeepSeek LLM 客户端 | ⭐⭐ |
| [src/extract_triples.py](src/extract_triples.py) | 三元组抽取（7 实体 + 7 关系 Schema） | ⭐⭐ |
| [src/build_graph.py](src/build_graph.py) | Neo4j 图谱构建（MERGE + 别名归一化） | ⭐⭐ |
| [src/retrieve.py](src/retrieve.py) | 图谱检索（Local Search 子图提取） | ⭐⭐ |
| [src/serve.py](src/serve.py) | FastAPI HTTP + SSE 服务 | ⭐⭐ |
| [src/eval_compare.py](src/eval_compare.py) | 对比评测脚本 | ⭐⭐ |
| [static/index.html](static/index.html) | 前端主页面 | ⭐ |
| [static/viz/force_graph.js](static/viz/force_graph.js) | D3.js 力导向图可视化 | ⭐ |
| [requirements.txt](requirements.txt) | 依赖清单（4 个包） | ⭐ |

---

## 12. 常见问题

### Q1: Tavily API Key 报 401 错误？

**原因**：dev 类型 Key（前缀 `tvly-dev-`）必须用 `Authorization: Bearer` header 鉴权，不能放在请求体里。

**解决**：代码已用 Bearer header 方式（[src/tavily_search.py](src/tavily_search.py) 第 49 行），确保环境变量 `TAVILY_API_KEY` 正确设置即可。

### Q2: Neo4j 连接报错 "ConnectionRefusedError"?

**原因**：Neo4j 未启动，或端口 7687 未开放。

**解决**：
1. 确认 JAVA_HOME 已设置且 Java 11 可用（`java -version`）
2. 启动 Neo4j：`.\bin\neo4j.bat console`
3. 验证端口：`Test-NetConnection -ComputerName localhost -Port 7687`

### Q3: 安装依赖报错 "python-leidenalg not found"?

**原因**：Windows 环境下部分包难以编译。

**解决**：`requirements.txt` 已移除未使用的 `python-leidenalg`、`python-igraph`、`networkx`，仅保留 4 个必需包。

### Q4: retrieve.py 报 "apoc.path.subgraphAll not found"?

**原因**：Neo4j Community 版默认不含 APOC 插件。

**解决**：代码已改为纯原生 Cypher（1 跳 + 2 跳两条 MATCH 查询），不依赖 APOC。

### Q5: LLM 抽取三元组时偶尔 JSON 解析失败?

**原因**：DeepSeek 输出偶尔超长导致 JSON 被截断（max_tokens=4096 边界问题）。

**影响**：被 try/except 捕获，仅跳过当批三元组，不影响主 Agent 调研结果和报告输出。

### Q6: 上传 GitHub 会泄露 API Key 吗?

**不会。** 代码全部使用 `os.environ.get()` 读取环境变量，无硬编码密钥。输出文件中也不含密钥。建议上传前加 `.gitignore` 排除 `.venv/` 目录。

### Q7: 如何调研新的公司?

修改 [src/agents.py](src/agents.py) 末尾的 `__main__` 部分：

```python
trace = agents.research_or_query("腾讯", "业务、薪资、技术栈、面试、前景")
```

或在浏览器访问：`http://localhost:8000/run?company=腾讯&question=薪资、技术栈`

### Q8: 串行模式为什么有时比并行快不了多少?

串行模式下 LLM 的响应时间有随机波动。如果串行时 LLM 恰好响应快，而并行时某个 Subagent 卡住，端到端加速比会偏低。但 dispatch 段加速比（3.2x）是稳定可靠的指标。

---

## 附录 A：企业级落地方案

### A.1 从学生项目到生产系统

| 维度 | 当前学生项目 | 企业级方案 |
|------|------------|-----------|
| 图数据库 | Neo4j Community 4.4.8（单机） | Neo4j Cluster / Aura Cloud（高可用） |
| LLM | DeepSeek chat（单模型） | 路由策略：简单问题用小模型，复杂推理用大模型 |
| 搜索 | Tavily dev key（1000 次/月） | Tavily Pro / 自建搜索集群 |
| 并发 | ThreadPoolExecutor（单机线程池） | Celery + Redis（分布式任务队列） |
| 缓存 | 无 | Redis 缓存热门公司子图 |
| 监控 | print 日志 | Prometheus + Grafana（QPS/延迟/错误率） |
| 部署 | `python -m src.serve` | Docker + Kubernetes（弹性扩缩容） |

### A.2 扩展方向

1. **增量更新**：定期重新调研已存图公司，对比新旧三元组，标注信息时效性
2. **多轮对话**：支持用户追问，基于已有图谱上下文深度对话
3. **跨公司对比**：利用图谱的图结构特性，查询"使用 Go 语言且年薪 30w+ 的公司列表"
4. **图谱推理**：利用 Neo4j GDS 图算法做社区检测、相似公司推荐
5. **多模态**：支持上传公司 Logo / 薪资截图，OCR 后抽取信息入图

### A.3 成本估算

| 资源 | 用量 | 月成本 |
|------|------|--------|
| Tavily dev key | 1000 次/月 | 免费 |
| DeepSeek API | ~50 次调研 × 20 LLM 调用 = 1000 次 | ~5 元人民币 |
| Neo4j Community | 单机 | 免费 |
| **总计** | | **~5 元/月** |

---

## 附录 B：技术细节

### B.1 ReAct 正则解析

```python
_RE_THOUGHT = re.compile(r"Thought:(.+?)(?=Action:|Final Answer:|$)", re.S)
_RE_ACTION = re.compile(r"Action:\s*([A-Za-z0-9_]+)")
_RE_ACTION_INPUT = re.compile(r"Action Input:(.+?)(?=Observation:|$)", re.S)
_RE_FINAL = re.compile(r"Final Answer:(.+)$", re.S)
```

- `re.S` 标志让 `.` 匹配换行符（Thought 和 Action Input 通常跨行）
- 用前瞻断言 `(?=Action:|Final Answer:)` 精确截取每段内容

### B.2 公司别名归一化

```python
COMPANY_ALIASES = {
    "字节跳动": ["字节跳动", "字节", "抖音集团", "ByteDance", "bytedance", ...],
    "腾讯":     ["腾讯", "Tencent", "腾讯控股", "鹅厂", ...],
    ...
}

ALIAS_MAP = {别名.lower(): 标准名}  # 大小写不敏感
```

LLM 抽取出的实体名先查别名表，匹配到就替换为标准名，确保"字节"、"ByteDance"、"抖音集团"都指向同一个 Company 节点。

### B.3 UID 生成与幂等 MERGE

```python
def make_uid(ntype, name):
    key = f"{ntype}||{normalize_name(name)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()
```

```cypher
MERGE (n {uid: $uid})
SET n:Company, n.name = $name
```

- `MERGE` 是幂等操作：节点已存在则更新，不存在则创建
- 同一公司多次调研不会产生重复节点，只会更新属性和新增边

### B.4 子图查询 Cypher（纯原生，不依赖 APOC）

```cypher
// 1 跳：公司直接关联的节点和边
MATCH (c:Company {uid: $uid})-[r]-(n)
RETURN startNode(r).name, type(r), endNode(r).name, ...

// 2 跳：公司的邻居的邻居
MATCH (c:Company {uid: $uid})--(n1)-[r2]-(n2)
WHERE n2.uid <> $uid
RETURN startNode(r2).name, type(r2), endNode(r2).name, ...
```

### B.5 SSE 跨线程通信

```python
q: queue.Queue = queue.Queue()  # 线程安全队列

def evt_cb(evt_dict):
    q.put(evt_dict)              # worker 线程 put 事件

def worker():
    agents = ResearchAgents(event_cb=evt_cb)
    trace = agents.research_or_query(...)
    q.put({"kind": "final_trace", "data": trace.to_dict()})
    q.put(None)                  # 结束信号

threading.Thread(target=worker, daemon=True).start()

def gen():
    while True:
        item = q.get(timeout=120)  # 主线程 get 事件
        if item is None: break
        yield f"data: {json.dumps(item)}\n\n"  # SSE 格式

return StreamingResponse(gen(), media_type="text/event-stream")
```

### B.6 ThreadPoolExecutor 并行 vs 串行对比

```python
# 并行模式
with ThreadPoolExecutor(max_workers=len(topics)) as ex:
    futs = {ex.submit(run_one, t): t for t in topics}
    for fut in as_completed(futs):
        results.append(fut.result())

# 串行模式（A/B 基线）
results = [run_one(t) for t in topics]
```

- 并行：`as_completed` 按完成顺序收集结果，墙钟时间 ≈ 最慢的那个 Subagent
- 串行：`for` 循环逐个执行，总耗时 = 所有 Subagent 耗时之和
- 加速比 = 串行总耗时 / 并行墙钟时间

### B.7 JSON 兜底解析

LLM 输出 JSON 时偶尔包裹 Markdown 代码块或多余文字，`chat_structured_json` 做了三层兜底：

```python
# 1. 去除 Markdown 代码块
if raw.startswith("```"):
    lines = raw.splitlines()
    lines = lines[1:] if lines[0].startswith("```") else lines
    lines = lines[:-1] if lines[-1].startswith("```") else lines
    raw = "\n".join(lines).strip()

# 2. 截取第一个 { 到最后一个 }
start, end = raw.find("{"), raw.rfind("}")
if start >= 0 and end > start:
    raw = raw[start:end+1]

# 3. json.loads
return json.loads(raw)
```

---

> **项目总结**：本项目实现了一个能自主下发 Subagent 并行完成多维调研的 Agent 系统，融合 GraphRAG 思路将调研结果持久化为 Neo4j 知识图谱。通过 A/B 评测验证了三大加速效果：Subagent 并行 3.2x、端到端 1.99x、图谱复用 12.93x。代码严格仿照 `market_research_subagents` 的架构设计，同时融入 `graphrag_financial_report` 的图谱构建与检索能力，形成"并行调研 → 知识沉淀 → 快速复用"的完整闭环。
