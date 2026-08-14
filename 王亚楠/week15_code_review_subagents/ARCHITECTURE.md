# ARCHITECTURE.md — 代码审查 Subagent 并行审查系统

## 1. 项目定位

**场景**：用户提交一个代码审查请求（指定文件/目录/项目），主审查 agent 自主决定是否派发多个子审查员从不同维度并行审查代码，聚合成结构化审查报告。直接落地「subagent 并行」范式。

**核心设计**：
- 主审查 agent 是 ReAct 循环，**有 4 个工具**：`read_file`（读文件）、`search_code`（搜索模式）、`list_files`（列目录）、`dispatch_reviewers`（派发多维度并行审查）。主 agent **根据审查范围自主决定**——单文件直接读，多文件/全项目必须派发。
- 子审查员也是 ReAct 循环（有 `read_file` + `search_code` + `list_files`），5 个维度（安全/性能/风格/逻辑/架构）用 `ThreadPoolExecutor` 并行执行 → 并行优势。
- 可视化：**左侧拓扑图**（主节点 + 派发时动态加入的维度节点），**右侧点任意节点看其 ReAct 过程**（Thought/Action/Observation），可不断切换。

**范式归属**：动态 Orchestrator-Workers（PPT 6.3）——主 agent 决定派几个维度，拓扑在运行时生长。

**与市场调研项目对比**：

| 维度 | 市场调研系统 | 代码审查系统 |
|------|------------|------------|
| **场景** | 联网调研市场信息 | 本地审查代码质量 |
| **核心工具** | web_search（联网搜索） | read_file / search_code（文件分析） |
| **子任务粒度** | 市场侧面（销量/竞争/政策） | 审查维度（安全/性能/风格/逻辑/架构） |
| **并行优势** | 多个搜索请求并行 | 多个审查维度并行 |
| **相同点** | Orchestrator-Workers + ThreadPool + SSE 流式 + ReAct 引擎 |

## 2. 整体流水线

```
用户审查请求
     ↓
主审查 agent ReAct 循环（工具: read_file + search_code + list_files + dispatch_reviewers）
     ├─ 单文件快速检查 → 直接 read_file/search_code → 报告
     └─ 全项目深度审查 → dispatch_reviewers("all" or "安全 | 性能 | 风格")
                             ↓
                ┌─ 安全审查员 ReAct（read_file/search_code/list_files） ─┐
                ├─ 性能审查员 ReAct（read_file/search_code/list_files） ─┤
                ├─ 风格审查员 ReAct（read_file/search_code/list_files） ─┤ 并行(ThreadPool)
                ├─ 逻辑审查员 ReAct（read_file/search_code/list_files） ─┤
                └─ 架构审查员 ReAct（read_file/search_code/list_files） ─┘
                             ↓ 汇总（含并行加速统计）
                主审查 agent 综合成结构化审查报告 → Final Answer
```

脚本对应：`file_tools.py`（文件分析工具）→ `react_loop.py`（通用 ReAct）→ `agents.py`（主 agent + 派发）→ `serve.py`（SSE）→ `eval_compare.py`（A/B）。

## 3. 各环节技术选型

### 3.1 文件分析工具（file_tools.py）
替代市场调研系统的 `tavily_search.py`。三个核心工具：
- `read_file`：读取代码（支持行范围，避免一次灌太多内容撑爆 context）
- `search_code`：grep 语义的代码模式搜索（支持正则、文件类型过滤、子目录限制）
- `list_files`：目录树展示（限制深度，跳过 node_modules/.git 等）

安全设计：所有路径操作限制在 `PROJECT_ROOT` 内（路径越界检测）。

### 3.2 通用 ReAct 引擎（react_loop.py）
主审查 agent 和子审查员共用同一个 `ReActLoop` 类，区别只在 `tools` 字典：
- 主审查 agent：`{read_file, search_code, list_files, dispatch_reviewers}`
- 子审查员：`{read_file, search_code, list_files}`

与市场调研项目的 ReAct 引擎内核相同，差异仅在工具注册表。

### 3.3 主审查 agent 自主决策（agents.py）
系统提示 `MAIN_SYSTEM` 给出明确决策原则 + worked example：
- 多文件/全项目审查 → **必须** `dispatch_reviewers` 派发 5 维度并行
- 单文件 → 直接 `read_file`/`search_code`

`dispatch_reviewers` 工具输入是 `安全 | 性能 | 风格`（管道分隔）或 `all`（全部 5 维度），支持中英文维度名。

### 3.4 审查维度设计
5 个维度各有专用系统提示（`SUB_REVIEWER_SYSTEM`）：
- **安全**：SQL 注入、XSS、命令注入、密钥泄露…
- **性能**：N+1 查询、嵌套循环、内存分配、阻塞 I/O…
- **风格**：命名规范、函数长度、注释质量、DRY…
- **逻辑**：空值处理、异常处理、资源泄漏、竞态条件…
- **架构**：模块耦合、循环依赖、设计模式、SOLID…

每个维度审查员有独立的 focus prompt，引导 LLM 从特定角度审查。

### 3.5 并行执行
`ThreadPoolExecutor(max_workers=N)` 并行跑 N 个维度审查员 ReAct。量化：`wall_clock`（并行墙钟）vs `serial_sum`（各审查员时长之和 = 串行基线）。

### 3.6 可视化（static/index.html）
- **深色科技主题**：渐变背景、玻璃卡片、发光节点
- **左侧拓扑**：主节点 + 维度节点（颜色编码：安全=红、性能=橙、风格=绿、逻辑=蓝、架构=紫）
- **右侧过程流**：全部实时流 + 按节点过滤 + 自动跟随滚动
- **底部报告**：结构化审查报告，带严重级别标记

## 4. 与市场调研系统的关键差异

| 层面 | 市场调研 | 代码审查 |
|------|---------|---------|
| 信息源 | Tavily 联网搜索 | 本地文件系统 |
| 数据特征 | 非结构化文本摘要 | 结构化代码（行号 + 文件路径） |
| 工具设计 | 单一 search 工具 | 三个互补工具（读/搜/列） |
| 派发粒度 | 市场分析侧面 | 代码审查维度 |
| 结果输出 | 分维度报告带来源 | 分严重级别（🔴🟡🟢💡）带行号 |
| 前端差异 | 搜索结果显示 | 代码行号显示 |
| 共同点 | ReAct × ThreadPool × SSE 流式 × 拓扑可视化 |

## 5. 实验结果预期

### 5.1 Parallel vs Serial A/B
| 审查范围 | 并行墙钟 | 串行墙钟 | dispatch 加速 |
|---------|---------|---------|--------------|
| 安全+性能+风格（3 维度） | ≈40s | ≈90s | ≈2.25× |
| 全部 5 维度（安全/性能/风格/逻辑/架构） | ≈60s | ≈180s | ≈3.0× |
| **平均** | **≈50s** | **≈135s** | **≈2.6×** |

加速比取决于各维度审查员耗时是否均匀——耗时越均匀，加速越大。

### 5.2 与 PPT 6.3/6.4 对应
- 拓扑：动态 Orchestrator-Workers（主 agent 派发，节点运行时生长）
- 用图理由（6.4）：多异构节点协作 ✓、可并行分支 ✓、需独立验证 ✓
- 并行 vs 顺序：serial 基线正是 6.4「顺序任务」对照，量化并行收益

## 6. 优化方向

| 层面 | 方向 |
|------|------|
| 审查质量 | 加代码静态分析工具（AST 解析替代 grep）、跨文件数据流分析 |
| 并行收益 | 主 agent 规划/综合用更便宜模型降串行占比 |
| 维度扩展 | 加测试覆盖率审查、文档质量审查、依赖安全审查 |
| 可视化 | diff 高亮显示、代码行内标注、修复建议一键应用 |
| 工程 | 大项目分批审查、文件数上限保护、LLM token 预算控制 |

## 7. 目录结构

```
code_review_subagents/
├── src/
│   ├── file_tools.py         # 文件分析工具（read_file/search_code/list_files）
│   ├── react_loop.py          # 通用 ReAct 引擎（主/子审查员共用）
│   ├── agents.py              # 主审查 agent + dispatch_reviewers 并行派发
│   ├── serve.py               # FastAPI + SSE 流式
│   ├── llm_client.py          # DeepSeek/Anthropic LLM 客户端
│   └── eval_compare.py       # parallel vs serial A/B
├── static/
│   └── index.html            # 左拓扑右 trace 审查可视化 UI
├── outputs/
│   └── eval_compare.json
├── requirements.txt
├── ARCHITECTURE.md
└── README.md
```
