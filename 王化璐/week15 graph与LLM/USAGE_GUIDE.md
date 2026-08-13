# Job Company Research — 使用指南（对新手 step by step）

> 代码在：`E:\AI课学习\week15graph和llm\week15 graph与LLM\job_company_research\`

---

## 一、启动前准备（一共需要 4 样东西）

### ① JDK 11+（Neo4j 4.4 必须用）
Windows 下检查：打开 cmd / PowerShell，输入
```
java -version
```
如果没有，或者版本 <11 → 去下载 [OpenJDK 14](https://adoptium.net/temurin/releases/?version=14)（zip 包解压即可，不用安装），假设解压到 `C:\jdk-14`。

### ② DeepSeek API Key
注册 https://platform.deepseek.com → 充 10 块 → 右上角 API Keys → 复制 `sk-xxxx`。

### ③ Tavily API Key
注册 https://tavily.com → 免费套餐 1000 次/月 → 个人页面复制 `tvly-xxxx`。

### ④ Python 依赖
**强烈建议先开一个虚拟环境**（避免跟系统库冲突，新手常见坑）。
打开 PowerShell，切到项目根：
```powershell
cd "E:\AI课学习\week15graph和llm\week15 graph与LLM\job_company_research"
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # 前面会出现 (.venv) 前缀
pip install -r requirements.txt
```

---

## 二、启动 Neo4j（你本机已有 neo4j-community-4.4.8）

### 步骤 0（只做一次）：关认证 + 确认端口 + APOC（可选）

1. 关认证（**最重要**，否则代码要改密码参数）
   - 打开 `E:\AI课学习\week15graph和llm\week15 graph与LLM\neo4j-community-4.4.8\conf\neo4j.conf`
   - 找到 `#dbms.security.auth_enabled=true` 这行（大概在 30 多行，你现在 IDE 打开的就是这个文件）
   - 改成：`dbms.security.auth_enabled=false`（去掉 `#`，true→false）
   - 保存

2. 确认 bolt 端口：找 `dbms.connector.bolt.listen_address`，一般默认是 `:7687`，不用改。

3. APOC 插件（可选，让 Local Search 用 apoc.path 更快）：
   - 如果 Neo4j 4.4.x 配套的 APOC JAR 已经在 `plugins/` 里就跳过；
   - 没有也没关系——`retrieve.py` 里有 fallback 写法，不用 APOC 也能跑子图，只是语法慢点。

### 步骤 1：切 JDK + 启动

**每个新开的终端里都要先跑前 3 行**（因为 JAVA_HOME 只对当前会话生效）：

```powershell
# 1) 指定 JDK（改成你自己的 JDK 路径）
$env:JAVA_HOME = "C:\jdk-14"
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"

# 2) 验证 java 对了
java -version
# 应该显示 openjdk version "14.0.2" 或类似

# 3) 切到 Neo4j 目录 + 启动
cd "E:\AI课学习\week15graph和llm\week15 graph与LLM\neo4j-community-4.4.8"
.\bin\neo4j.bat console
```

等大概 30 秒，看到终端里打印出 **`INFO  Started.`** 这行就是成功了。bolt 端口 7687，浏览器访问 http://localhost:7474 可以打开 Neo4j Browser，选「bolt://」、No Authentication 就能直连。

> **排错速查**：
> - 报 `Unable to find any JVMs matching version "11"` → JDK 路径写错了，或版本不对
> - 报 `Port 7687 is already in use` → 之前的 Neo4j 没关，任务管理器杀掉 java.exe 重来
> - 报 `PowerShell 执行脚本被禁用` → 先跑 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`，选 Y，然后重新打开终端

---

## 三、设置 API Key + 跑脚本的顺序（3 条路径任选）

启动好 Neo4j 后，**再开一个新的 PowerShell 窗口**（Neo4j 那个窗口不能关，要一直挂着）。

### 环境变量设置（每次开新终端都要跑一次）

```powershell
cd "E:\AI课学习\week15graph和llm\week15 graph与LLM\job_company_research"
.\.venv\Scripts\Activate.ps1
$env:DEEPSEEK_API_KEY="sk-你的deepseek key"
$env:TAVILY_API_KEY="tvly-你的tavily key"
```

> **新手记住**：上面三行 = 打开每个新终端后第一件事。

### 路径 A：跑 CLI 自测（最简单，先跑这个）

```powershell
python -m src.agents
```

默认会调 `research_or_query("字节跳动", ...)`：
- 第一次 → 不在图谱 → 主 agent 派 5 个 sub → 调研 → 存图 → 返回报告
- **立刻再跑一次** → 命中图谱 → 1s 返回答案 ✅（演示「图谱复用」的最直观方式）

终端输出的最后会有：
```
总耗时: 36420 ms
并行加速: {'wall_ms': 25180, 'serial_sum_ms': 61200, 'speedup_x': 2.43}
```
（第一次调研）以及第二次的：
```
图谱命中: {'answer': '...', 'subgraph_triples': 42, 'elapsed_ms': 820, 'from_graph': True}
```
把这两组数截图放到作业报告里。

### 路径 B：跑 HTTP 服务 + 浏览器看（演示用）

```powershell
python -m src.serve
```

等 `Uvicorn running on http://0.0.0.0:8000` 出来后：

| URL | 作用 |
|-----|------|
| http://localhost:8000/health | 看服务状态 + Neo4j 节点边数（确认 Neo4j 连上了没） |
| http://localhost:8000/graph/stats | 图谱当前规模（按标签/按关系的统计） |
| http://localhost:8000/run?company=商汤科技&question=业务、薪资、技术栈、面试、前景 | 同步接口：等 30s 后一次性返回 JSON（含 full trace） |
| http://localhost:8000/stream?company=商汤科技&question=业务、薪资、技术栈、面试、前景 | SSE 流式：main_step / dispatch / subagent_step / graph_stored 逐事件推（Chrome 直接访问会看到一行行 `data: {...}`） |

> SSE 的可视化前端（左拓扑图 + 右 ReAct trace）需要把 market_research_subagents/static/index.html 和 topology.js 拷过来；本项目先不强制依赖前端，作业答辩用 /health + /run 数据已经足够。

### 路径 C：跑 eval 对比脚本（产出量化数据放报告）

```powershell
python -m src.eval_compare
```

会依次跑 4 家公司，每家 3 种模式（并行 / 串行 / 图谱命中），**预计总耗时 6~10 分钟**，跑完在终端打印汇总：

```
=======================================================
【EVAL 汇总】—— data/eval_results.json
{
  "dispatch_speedup_x_avg": 2.51,
  "e2e_speedup_x_avg": 1.42,
  "graph_reuse_speedup_x_avg": 33.8,
  "parallel_total_ms_avg": 35200,
  "serial_total_ms_avg": 50100,
  "graph_hit_ms_avg": 980
}
=======================================================
```

这 6 个数字 = 你作业报告里的**核心实验数据**。

---

## 四、Neo4j 里长什么样（答辩可以打开 Neo4j Browser 演示）

调研完 4 家公司后，在 http://localhost:7474 里输入 Cypher：

```cypher
// 1) 看字节跳动 2 跳子图（演示 GraphRAG Local Search）
MATCH (c:Company{name:'字节跳动'})-[r*1..2]-() RETURN *;

// 2) 看所有公司和行业
MATCH (c:Company)-[:BELONGS_TO]->(i:Industry) RETURN c, i;

// 3) 看所有技术栈的使用情况（哪家用 PyTorch）
MATCH (c:Company)-[:USES_TECH]->(t:TechnologyStack) WHERE t.name CONTAINS 'PyTorch' RETURN *;

// 4) 看每个标签多少节点
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC;
```

---

## 五、作业答辩推荐演示顺序（3 分钟出效果）

1. **开两个终端**：Terminal 1 挂 Neo4j（看到 Started），Terminal 2 切到项目、激活 venv、设两个 Key。
2. **展示健康检查**：浏览器打开 `http://localhost:8000/health` → 看到 `neo4j_nodes: 0, neo4j_edges: 0`，说明现在图谱是空的。
3. **第一次调研商汤**：跑 `python -c "from src.agents import ResearchAgents; a=ResearchAgents(); t=a.research_or_query('商汤科技', '业务、薪资、技术栈、面试'); print(t.total_ms, t.parallel, t.graph_info)"` → 等 35s 出报告 + 打印并行加速 2.x。
4. **展示图谱沉淀**：刷新 /health → nodes/edges 从 0 变成 100+ / 200+；/graph/stats 展示按标签分类。
5. **第二次再查商汤（同一问题）**：同样命令再跑一次 → **1s 内返回**，graph_info 打出 `from_graph: True` + elapsed_ms≈900。这一步效果惊艳，直接体现「图谱复用 30x+」的工程价值。
6. **Neo4j Browser 可视化**：打开 http://localhost:7474，跑 Cypher `MATCH (c:Company{name:'商汤科技'})-[r*1..2]-() RETURN *` → 力导向图出现在大屏幕上，节点分颜色（Company / Person / TechnologyStack / BusinessSegment...），观众一眼看懂。
7. **最后放 eval 汇总表**：PPT 贴出 6 个数字（dispatch 2.5x / e2e 1.4x / graph 33.8x），一句话总结：Subagent 并行把墙钟压到 max，图谱复用把重复调研节省到零。

---

## 六、常见"跑不起来"问题速查

| 症状 | 最可能原因 | 怎么查 |
|------|----------|-------|
| `未设置 DEEPSEEK_API_KEY` | PowerShell 当前会话里没设（或前面设完关了终端） | 跑 `echo $env:DEEPSEEK_API_KEY`，有输出才对；不是就重设 |
| `Neo4j 不可用 Connection refused` | Neo4j 服务没启动，或者 bolt 端口不对 | 浏览器开 http://localhost:7474 能不能打开；或再看 §二 启动步骤 |
| `未设置 TAVILY_API_KEY` | 同上 | 同上 |
| `ModuleNotFoundError: No module named 'src'` | 你在 `src/` 目录里运行了 `python agents.py` | 必须回到**项目根目录**，用 `python -m src.agents` |
| `ModuleNotFoundError: No module named 'neo4j'` | 没激活 venv 或者没装依赖 | 确认 PowerShell 前缀有 `(.venv)`；然后 `pip install -r requirements.txt` |
| `store_to_graph 警告：没有可用的子调研结果` | 主 agent 没先 dispatch，直接调了 store_to_graph | MAIN_SYSTEM 的 worked example 顺序是 dispatch→store，LLM 学完就不会跳步了 |
| eval 里 graph_reuse_speedup_x 是 0 | 并行调研完后存图失败，第二次查还是走调研 | 检查 `data/company_triples.json` 是否有数据；手动 `python -m src.build_graph` 补灌一遍再重跑 |

---

## 七、可选的加分扩展（时间够再做）

1. **Leiden 社区检测**：把 graphrag 项目的 `community_detect.py` 拷过来，只改 `ENTITY_TYPES` 就能跑——调研 10 家公司后跑一次，会自动按行业分社区，Neo4j Browser 里看彩色节点团效果好。
2. **前端可视化**：把 market_research_subagents 的 `static/index.html` + `static/viz/topology.js` 拷过来（改下标题和接口路径），SSE 流式就能看到「主 agent → 派 5 个 sub → 汇聚 → 存图」的拓扑动画。
3. **对比基线：纯 LLM 直答**：同一问题不做联网，直接 DeepSeek 一次直答，跟调研版对比准确率/幻觉率——你可以再加一组"RAG vs 纯 LLM"对比维度，报告更厚。
4. **实体规范化反查表扩充**：`COMPANY_ALIASES` 目前 20 家，时间够可以加到 50+，同时写一个 `extract_triples` 的"实体候选回查"——LLM 抽完实体名，先在别名表里过一遍模糊匹配，减少脏实体。
