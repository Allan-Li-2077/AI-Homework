# ARCHITECTURE.md — Agent 记忆系统 + Skills 技能执行 技术方案

## 一、项目定位

### 教学场景
本项目演示 **AI Agent 的四层记忆体系 + Skills 技能系统 + 自主调度能力**，回答三个核心问题：
> "ChatGPT 为什么每次都忘掉你？怎样让 AI 真正记住你？"
> "Agent 能不能主动做事，而不是只等用户问？"
> "如何让 LLM 可靠地操作本地文件和脚本？"

通过一个有持久记忆的个人助手，学生能亲眼看到：
1. 每条消息如何从四层记忆中组装 Context
2. 会话结束后 Memory Flush 如何将信息写入长期记忆
3. Skills 系统如何让 LLM 通过生成 Python 脚本操作本地文件
4. HEARTBEAT 如何让 Agent 具备定时主动行动的能力
5. 下次对话时，助手已经"认识"你了


---

## 二、四层记忆模型

```
┌─────────────────────────────────────────────────────────────┐
│                     Context Window（LLM 输入）                │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Layer 3     │  │  Layer 4     │  │  Layer 2         │  │
│  │  Markdown 文件│  │  混合检索    │  │  SQLite 会话历史  │  │
│  │  SOUL.md     │  │  FAISS+FTS5  │  │  当轮对话消息     │  │
│  │  USER.md     │  │  向量+BM25   │  │  多轮上下文       │  │
│  │  MEMORY.md   │  │  Top-K 条目  │  │                  │  │
│  │  AGENTS.md   │  │              │  │                  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘

            ↑ 对话结束后触发 ↑
┌─────────────────────────────────────────────────────────────┐
│                    Memory Flush                              │
│  Pass 1: 对话 → LLM 提取用户信息 → USER.md                   │
│  Pass 2: 对话 → LLM 提取记忆条目 → MEMORY.md + 每日日志       │
│  Pass 3: 新条目 → Embedding → FAISS + FTS5 同步更新           │
│  可选:   条目数 > 50 → Compaction（LLM 压缩旧条目，重建双索引）│
└─────────────────────────────────────────────────────────────┘

            ↑ 常驻后台 ↑
┌─────────────────────────────────────────────────────────────┐
│                HEARTBEAT 调度器                               │
│  解析 HEARTBEAT.md → APScheduler 注册 cron job               │
│  任务触发 → LLM 执行 → SSE 广播到前端（紫色气泡）              │
│  对话中检测调度/取消意图 → 自动更新 HEARTBEAT.md → 热重载      │
└─────────────────────────────────────────────────────────────┘
```

### 各层职责

| 层级 | 内容 | 持久化 | 查询方式 | 对应文件 |
|------|------|--------|---------|---------|
| Layer 1 工作记忆 | 当次 LLM 调用的完整 Context | 否（随请求消失）| 直接注入 | — |
| Layer 2 短期记忆 | 当前会话对话历史（SQLite）+ 每日日志（今+昨）| 是（DB + `memory/YYYY-MM-DD.md`）| 顺序读取 / 日志全量注入 | `src/session_db.py`、`src/memory_loader.py` |
| Layer 3 长期记忆 | Markdown 配置文件 | 是（.md 文件）| 全量注入（近期条目）| `src/memory_loader.py` |
| Layer 4 语义记忆 | FAISS 向量索引 + FTS5 全文索引 | 是（二进制 + SQLite FTS5）| 混合检索：向量 0.7 + BM25 0.3，取并集 | `src/vector_store.py`、`src/fts_store.py`、`src/retrieval.py` |

---

## 三、Skills 技能系统

### 设计理念

Skills 系统让 LLM 能够操作本地文件：生成 HTML、运行脚本、创建数据文件等。核心理念是 **"LLM 只写 Python 代码，不写 Shell 命令"**——完全消除了 JSON → Shell → Python 三层嵌套转义问题。

```
用户说"给我做一张 crazy 的闪卡"
    │
    ▼
[agent.py / serve.py]      第一阶段 LLM 调用
    │   System Prompt 包含技能简介列表（渐进式披露）
    │   LLM 判断需要技能 → 输出 [SKILL: flash-card]
    ▼
[skill_loader.py]          加载 skills/flash-card/SKILL.md 完整说明
    │   注入 build_script_prompt() 要求 LLM 输出 Python 脚本
    ▼
第二阶段 LLM 调用
    │   LLM 生成 ```python ... ``` 代码块
    │   例如: json.dumps → Path.write_text → subprocess.run → webbrowser.open
    ▼
[task_planner.py]          ScriptExecutor 执行引擎
    │   1. extract_python_script() 从 LLM 输出提取脚本
    │   2. 保存到 outputs/skill_scripts/<timestamp>.py
    │   3. subprocess.run([python, script_path]) 执行
    │   4. _cleanup_script() 删除临时文件
    ▼
输出结果 + 打开预览（webbrowser）
```

### 为什么用「脚本模式」而不是「JSON 命令模式」

| 对比维度 | 旧 JSON 模式 | 新脚本模式 |
|---------|-------------|-----------|
| LLM 输出 | JSON 含 shell 命令字符串 | Python 代码块 |
| 转义层数 | JSON → Shell → Python（三层） | 仅 Python（零层） |
| 数据写入 | `python3 -c "json.dump({...})"` 引号地狱 | `Path("x.json").write_text(json.dumps(...))` |
| 错误原因 | 引号不匹配、JSON 格式错误 | 普通 Python 语法错误 |
| 调试方式 | 无法直接运行 | 脚本文件可手动运行调试 |
| 安全策略 | 白名单首词 + 引号剥离正则 | Python subprocess 无 shell 注入 |
| 临时文件处理 | 无（命令在 shell 中直接执行） | 保存 → 执行 → 自动删除 |

### 渐进式披露：两层 LLM 调用

```
第一层（轻量 Skill 列表）
  System Prompt 仅含技能名称 + 一句话简介：
  - flash-card: 为英语单词生成 HTML 闪卡
  - baoyu-diagram: 创建暗色主题 SVG 图表

  LLM 判断是否需要技能 → 输出 [SKILL: flash-card]

第二层（完整 Skill 说明）
  System Prompt 含 SKILL.md 完整内容 + build_script_prompt()
  LLM 获得执行流程、脚本路径、数据格式等全部细节 → 生成 Python 脚本
```

### Skills 目录结构

```
skills/
├── flash-card/                  # 闪卡技能
│   ├── SKILL.md                 # 技能描述（name / description / 执行流程）
│   ├── data/                    # 单词 JSON 数据（crazy.json 等）
│   └── scripts/
│       └── make_flashcard.py    # 数据 → HTML 转换脚本
│
└── baoyu-diagram/               # 图表技能
    ├── SKILL.md                 # 技能描述（设计系统 / 布局规则 / SVG 规范）
    ├── references/              # 各图表类型参考（architecture.md 等）
    └── scripts/
        └── main.ts              # SVG → @2x PNG 转换脚本（需 bun 运行时）
```

### SKILL.md 格式

```yaml
---
name: flash-card
description: >-
  为一个英语单词生成静态 HTML 学习闪卡...
---

# Flash Card 单词闪卡生成

## 触发场景
...

## 执行流程
1. 识别单词
2. 生成 JSON 数据 → skills/flash-card/data/<word>.json
3. 运行脚本 → python skills/flash-card/scripts/make_flashcard.py
4. 打开预览 → webbrowser.open()
```

### 脚本生成 Prompt 设计要点

`build_script_prompt()` 在 `task_planner.py` 中定义（第 945-1030 行附近）。关键设计：
- **示例驱动**：给 LLM 一个完整、可运行的示例脚本（含 import / 数据构建 / subprocess.run / webbrowser.open 完整流程）
- **标准库限定**：明确要求只使用 `json` / `subprocess` / `webbrowser` / `pathlib` 等标准库，不依赖第三方包
- **禁止 shell 命令**：要求用 `Path().write_text()` 替代 `python3 -c`，用 `subprocess.run([...], check=True)` 替代 shell 字符串
- **构建字符串规则**：要求用相对路径、避免反斜杠转义，中文内容直接用 Unicode

### ScriptExecutor 执行流程

```
extract_python_script(llm_output)
  ├── 优先匹配 ```python ... ``` 代码块
  ├── 回退 ``` 任意代码块（_looks_like_python 判断）
  └── 兜底：找最长 Python 关键字开头的段落

保存脚本 → outputs/skill_scripts/<timestamp>_<slug>.py
  ├── 用户确认（confirm=True 时展示前 30 行预览）
  └── auto_approve 模式跳过确认

subprocess.run([sys.executable, script_path], timeout=120)
  ├── 成功 → _cleanup_script() 删除临时文件
  ├── 失败 → _cleanup_script() + 返回 stderr
  └── 超时 → _cleanup_script() + 错误消息

返回 Dict[str, str] → format_script_summary() → 显示给用户
```

### command_executor.py（旧格式兼容）

保留 `handle_exec_tag()` 和 `execute_command()` 用于处理 `[EXEC: ...]` 标记格式的 LLM 输出（非技能场景下的命令执行）。包含完整的安全策略：白名单首词、转义感知引号剥离、路径限制。`ScriptExecutor` 不再走此路径，仅独立的 `[EXEC:]` 标记使用。

---

## 四、记忆系统整体流水线

```
用户输入
    │
    ├── [后台并行] heartbeat_parser.py
    │     正则初筛 → 命中 → LLM 判断新建/取消意图
    │     → 更新 HEARTBEAT.md → 调度器热重载
    │
    ├── [技能检测] 第一阶段 LLM 判断是否需要技能
    │     命中 → 加载 SKILL.md → 第二阶段 LLM 生成 Python 脚本
    │     → ScriptExecutor 保存/执行/清理 → 输出结果
    │
    ▼
[memory_loader.py]  读取 SOUL.md + 每日日志（今+昨）+ USER.md + AGENTS.md + MEMORY.md（近10条）
    │                → 组装 Base System Prompt
    ▼
[retrieval.py]       HybridRetriever：query 同时走 FAISS 语义 + FTS5/BM25 关键词
    │                 → 0.7 向量 + 0.3 BM25 加权并集 → Top-3 相关记忆
    ▼
[session_db.py]     get_session_messages() → 读取当前会话历史（Layer 2）
    ▼
[serve.py]          拼接 Context Window → 调用 LLM → 流式输出（SSE /chat）
    ▼
用户收到回复
    │
    ▼  会话消息写入 SQLite（add_message × 2）
    │
    ▼  （消息数 ≥ 20 / 用户 /flush）
    │
[memory_flush.py]
    ├── Pass 1: get_session_messages() → LLM 提取用户信息 → 更新 USER.md
    ├── Pass 2: LLM 提取记忆条目 → 追加 MEMORY.md + 写入 memory/YYYY-MM-DD.md 每日日志
    ├── Pass 3: 新条目 Embedding → 同步写入 FAISS + FTS5
    └── 可选: Compaction（条目 > 50 → LLM 压缩 → 重建 FAISS + FTS5）
        mark_flushed() → SQLite 标记已处理
```

---

## 五、Markdown 作为记忆配置语言

### 设计理念

| 传统方式 | Markdown 方式 |
|---------|-------------|
| JSON/YAML 配置（人不友好）| 纯 Markdown（人类直接可读可编辑）|
| 数据库存储（需要工具查看）| 文件系统（Git 可追踪、可 diff）|
| 固定 Schema（改字段需改代码）| 自由格式（LLM 原生理解）|

### 各文件职责

| 文件 | 职责 | 更新方式 |
|------|------|---------|
| `SOUL.md` | Agent 人格、沟通风格、能力边界声明 | 仅手动编辑 |
| `USER.md` | 用户画像（姓名/职业/偏好）| Memory Flush Pass 1 自动更新 |
| `MEMORY.md` | 跨会话持久记忆条目 | Memory Flush Pass 2 自动追加 |
| `AGENTS.md` | 操作规范、记忆使用原则、Agent 能力声明 | 仅手动编辑 |
| `HEARTBEAT.md` | 定时任务定义（cron 表达式 + action）| 对话意图检测自动写入 + 手动编辑 |
| `YYYY-MM-DD.md` | 每日日志（近端记忆）：当天 Flush 提取的条目，append-only | Memory Flush Pass 2 自动追加，会话启动加载今+昨 |

### MEMORY.md 条目格式
```markdown
### [category] 标题
记录时间：YYYY-MM-DD HH:MM

详细内容（2~4 句话）
```
category 取值：`preference` | `fact` | `event` | `decision`

---

## 六、Memory Flush 技术细节

### 为什么用 LLM 而不是规则提取？
用户不会说"我的偏好是咖啡"，会说"最近天气热，每天都要来一杯美式"。LLM 能跨句推断、识别隐式偏好；规则提取只能处理显式信息，覆盖率极低。

### Pass 1 两步设计
```
Step 1a: 对话 → LLM → JSON 数组（field / value / confidence）
Step 1b: 当前 USER.md + 新信息 JSON → LLM → 更新后的完整 USER.md
```
两步分离：1a 是语义理解，1b 是结构化写作。合并为一步时 LLM 容易混淆任务边界。

### Compaction 机制
```
条件：MEMORY.md 条目数 ≥ 50
策略：保留最新 20 条不变 + 最早 30 条 → LLM 压缩为 ~5 条摘要 → 重建 FAISS + FTS5 双索引
类比：Claude Code 的上下文压缩（/compact 命令）
```

---

## 七、HEARTBEAT 机制

### 架构总览

HEARTBEAT 系统由三个组件协作实现"Agent 自主调度"：

```
heartbeat_parser.py   ← 读写 HEARTBEAT.md、检测对话意图
scheduler.py          ← APScheduler 调度 + 任务执行 + SSE 广播
serve.py              ← 意图检测触发入口 + /stream SSE 端点
```

### HEARTBEAT.md 格式

```markdown
<!-- TASKS_START -->
### TASK: morning_reminder
trigger: 0 8 * * 1-5
enabled: true
action: send_message
description: 工作日早上8点发送问候
prompt: 根据用户画像生成个性化早安问候
added: 2026-05-08
<!-- TASKS_END -->
```

字段说明：
- `trigger`：标准 5 字段 cron 表达式
- `enabled`：`false` 等于软删除，调度器不加载但文件保留记录
- `action`：`send_message` / `summarize_sessions` / `compact_memory` / `user_profile_refresh`
- `prompt`：仅 `send_message` 时使用，LLM 生成消息的指令

### 任务新建流程（对话驱动）

```
用户说"每天早上8点提醒我喝水"
    │
    ▼ asyncio.create_task()（不阻塞回复）
    │
CANCEL_PATTERNS 正则初筛
    → 未命中，继续
SCHEDULE_PATTERNS 正则初筛（10条规则，零成本）
    → 命中
    │
    ▼ run_in_executor（线程池，不阻塞 event loop）
    │
LLM 判断（analyze_and_write）
    → 输出 JSON：{name, trigger, action, description, prompt}
    │
    ▼
_append_task() → 追加到 HEARTBEAT.md TASKS 块
    │
    ▼
hb_scheduler._load_tasks() → 立即重载，注册新 job
    │
    ▼
broadcast("heartbeat_task_added") → 前端紫色气泡提示
```

### 任务取消流程

```
用户说"取消早上的提醒"
    │
    ▼ CANCEL_PATTERNS 正则命中
    │
LLM 判断（analyze_and_cancel）
    → 展示已启用任务列表，输出 {cancel: true, name: "..."}
    │
    ▼
_disable_task() → enabled: true → enabled: false
    │
    ▼
hb_scheduler._load_tasks() → 立即重载，job 被移除
    │
    ▼
broadcast("heartbeat_task_cancelled") → 前端气泡提示
```

**取消与新建的优先级**：`_check_schedule_intent` 中先检测取消意图，命中后直接 `return`，不再检测新建，两者互斥。

### 调度器热重载机制

```
服务启动 → _load_tasks()（首次加载）
         → 额外注册 interval/60s 的 _check_reload job

_check_reload（每60秒）：
    检查 HEARTBEAT.md mtime
    → 有变化 → _load_tasks()（清除旧 job，重新注册）

主动触发（立即生效）：
    对话意图写入任务后 → 直接调 _load_tasks()
    /reset 后 → 直接调 _load_tasks()
```

### 任务执行与 SSE 广播

```
APScheduler 触发（同一 event loop）
    │
    ▼
_execute_task(task)
    → broadcast("heartbeat_start", ...)
    → _action_xxx(task)（根据 action 类型执行，LLM 调用走 run_in_executor）
    → broadcast("heartbeat_message", {message: "..."})

broadcast(type, data)
    → payload 写入所有 _stream_listeners 中的 asyncio.Queue
    → /stream 端点的 async generator 消费 Queue → yield → 推给浏览器
    → 前端 EventSource onmessage → 聊天流插入紫色气泡
```

### SSE 长连接保活

浏览器通过 `EventSource('/stream')` 维持持久连接。服务端每 20 秒发送 `: keepalive\n\n` SSE 注释行，防止 Uvicorn 的 keep-alive 超时（默认 5 秒）关闭连接。每个浏览器连接对应一个独立的 `asyncio.Queue`，`broadcast` 向所有 Queue 推送同一条消息。

---

## 八、SQLite 数据库设计

### 表结构

```sql
CREATE TABLE sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time  TEXT NOT NULL,    -- 会话创建时间
    end_time    TEXT,             -- 关闭时间（NULL = 当前活跃会话）
    title       TEXT,             -- 取第一条消息前30字
    flushed     INTEGER DEFAULT 0 -- 0=未Flush，1=已Flush
);

CREATE TABLE messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    role        TEXT NOT NULL,    -- "user" 或 "assistant"
    content     TEXT NOT NULL,
    timestamp   TEXT NOT NULL
);

-- Layer 4 关键词检索（FTS5 全文索引，由 fts_store.py 管理）
CREATE VIRTUAL TABLE memory_fts USING fts5(
    entry_id UNINDEXED,          -- 与 FAISS metadata 的 id 对齐，用于混合并集
    title,                       -- 逐字分词后的标题（中文逐字空格分隔）
    content,                     -- 逐字分词后的正文
    category UNINDEXED,
    title_raw UNINDEXED,         -- 原文，检索结果回显用
    content_raw UNINDEXED
);
```

`sessions`/`messages` 由 `session_db.py` 管理，`memory_fts` 由 `fts_store.py` 管理，三者同库（`outputs/sessions/memory.db`）。`memory_fts` 不存原始向量（向量在 FAISS），只做 BM25 关键词检索，与 FAISS 语义检索在 `retrieval.py` 中混合。

### 写入时机

| 操作 | 位置 | 写入内容 |
|------|------|---------|
| 服务启动 / `/new` / `/reset` | `lifespan` / `/session/new` / `/reset` | `INSERT INTO sessions`，建空会话 |
| 每条对话完成 | `/chat` Step 5 | `INSERT INTO messages` × 2（user + assistant）|
| 会话关闭 | `close_session()` | `UPDATE sessions SET end_time, title` |
| Flush 完成 | `/flush` 末尾 | `UPDATE sessions SET flushed=1` |

### 查询时机

| 查询方法 | 调用位置 | 用途 |
|---------|---------|------|
| `get_session_messages(sid)` | `/chat` 每次请求 | 拼入 LLM messages 作为多轮历史（Layer 2）|
| `get_session_messages(sid)` | `/flush` 开始时 | 传给 MemoryFlusher 做记忆提取 |
| `get_message_count(sid)` | `/chat` 流结束时 | 判断是否触发自动 Flush（≥20条）|
| `get_today_messages()` | scheduler `summarize_sessions` | 今日全部消息 → LLM 汇总 |
| `get_recent_sessions(5)` | `GET /memories` | 右侧面板历史会话数展示 |
| `retriever.search(query)` | `/chat`、`/layers`、CLI 每轮 | Layer 4 混合检索 Top-K（向量 0.7 + BM25 0.3 并集）|
| `fts_store.search(query)` | `retriever` 内部调用 | BM25 关键词召回（中文逐字分词，min-max 归一）|

### 连接方式

每次操作独立建立连接，无连接池、无持久连接，避免 SQLite 文件锁冲突。`session_db.py` 用 `with self._connect() as conn`（事务作用域，连接由 GC 回收）；`fts_store.py` 改用显式 `conn.close()`——`with` 在 Windows 上不会及时关闭句柄，曾导致 `/reset` 后文件被锁无法清理 `memory_fts`。`/reset` 时直接 `DELETE FROM messages; DELETE FROM sessions; DELETE FROM memory_fts` 保留 schema 清空数据。

---

## 九、LLM 提供商配置

所有 LLM 对话调用通过 `src/llm_config.py` 统一管理，由环境变量 `LLM_PROVIDER` 切换。

| 提供商 | 模型 | 环境变量 | 默认 |
|--------|------|---------|------|
| DeepSeek | `deepseek-v4-flash` | `DEEPSEEK_API_KEY` | ✅ |
| DashScope | `qwen-plus` | `DASHSCOPE_API_KEY` | 备选 |

Embedding 固定使用 DashScope `text-embedding-v3`（DeepSeek 无 Embedding API），切换 `LLM_PROVIDER` 不影响向量化流程。

---

## 十、技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 对话 LLM | DeepSeek-v4-flash（默认）/ Qwen-plus | OpenAI 兼容接口，切换只改 base_url |
| Embedding | DashScope text-embedding-v3 | 单批 ≤10 条，1536 维，质量稳定 |
| 向量库 | FAISS IndexFlatIP + L2 归一化 | 本地运行无需网络，内积 = 余弦相似度 |
| 全文索引 | SQLite FTS5 + bm25() | 零依赖（stdlib自带），与 SQLite 同库，BM25 关键词检索互补向量语义 |
| 会话存储 | SQLite | 零配置，单文件，教学场景够用 |
| 调度器 | APScheduler AsyncIOScheduler | 嵌入 FastAPI 同一 event loop，无需额外进程 |
| Web 框架 | FastAPI + uvicorn | lifespan 管理单例，SSE 流式推送 |
| 技能执行 | Python subprocess | LLM 生成脚本 → 文件 → 执行 → 清理，消除转义问题 |

---

## 十一、关键工程决策与踩坑

### 记忆系统

| 问题 | 根因 | 解法 |
|------|------|------|
| Memory Flush 提取率低 | 规则提取只处理显式信息 | Two-Pass LLM：先提取结构化 JSON，再写文档 |
| LLM 输出带代码块包裹 | Instruct 模型习惯 ` ```markdown ` 包裹 | `_strip_code_fence()` 写文件前去除包裹 |
| JSON 解析失败 | LLM 输出夹杂解释文字 | 正则提取第一个 `{...}`，`json.loads` 兜底 |
| FAISS 余弦相似度错误 | `IndexFlatIP` 做的是内积，非余弦 | 向量写入前 L2 归一化，使内积 = 余弦相似度 |
| Compaction 后索引过期 | MD 压缩但 FAISS/FTS5 未同步 | Compaction 后调 `rebuild_from_entries()` 重建 FAISS + FTS5 |
| SSE 长连接被断开 | Uvicorn keep-alive 超时默认 5 秒 | 每 20 秒发 `: keepalive\n\n` 注释行保活 |
| /reset 不停止定时任务 | 文件重置了，但 APScheduler job 在内存中 | reset 后立即调 `hb_scheduler._load_tasks()` |
| 调度意图被模型否认 | 模型系统提示里没有声明具有此能力 | 在 AGENTS.md 中明确声明可设置/取消定时任务 |
| Windows SQLite 文件锁 | `with conn` 不关闭句柄，服务运行时无法 unlink/清表 | `fts_store.py` 显式 `conn.close()`；`/reset` 用 `DELETE FROM messages/sessions/memory_fts` 保留 schema |
| 中文 FTS5 召回失效 | `unicode61` 把整段中文当一个 token | 逐字空格分词，每汉字独立 token |
| BM25 与向量分不可比 | SQLite `bm25()` 返回负值，量纲与余弦不同 | 取反后 min-max 归一到 [0,1]，再与向量按 0.7/0.3 加权取并集 |
| 混合检索降级 | FTS5 扩展可能未编译进 sqlite3 | `fts_store.available=False` 时 `search` 返回 []，`HybridRetriever` 自动退化为纯向量 |
| Windows OpenMP 冲突 | torch/numpy 各自链接 libiomp5md.dll | 所有脚本顶部加 `KMP_DUPLICATE_LIB_OK=TRUE` |

### Skills 技能执行

| 问题 | 根因 | 解法 |
|------|------|------|
| JSON 模式下 LLM 命令生成易出错 | JSON → Shell → Python 三层嵌套转义，引号冲突频繁 | 切换为脚本模式：LLM 输出 ````python ```` 块，系统保存文件后 subprocess 执行 |
| LLM 输出 python3 -c 引号错误 | 单引号/双引号在 Shell 和 Python 间传递时语义变化 | 不再使用 python3 -c，改用 `Path().write_text(json.dumps(...))` |
| 脚本执行后残留临时文件 | 原 ScriptExecutor 未实现清理 | 新增 `_cleanup_script()` 辅助函数，成功/失败/超时三处出口均调用 |
| 渐进式披露避免 Prompt 过重 | SKILL.md 详细信息不适合每次注入 | 两层 LLM 调用：第一层仅含技能简介 → [SKILL: xxx] → 第二层才加载完整 SKILL.md |
| bun 转换 PNG 失败（非致命） | 环境未安装 bun 运行时 | 脚本中 try/except 捕获，SVG 已生成即可，PNG 转换失败仅打印警告 |

---

## 十二、目录结构

```
agent_excise/
├── src/
│   ├── session_db.py         # Layer 2：SQLite 会话历史（读写/查询）
│   ├── memory_loader.py      # Layer 3：Markdown + 每日日志 → System Prompt 组装
│   ├── vector_store.py       # Layer 4：FAISS 向量库（Embedding + 语义检索）
│   ├── fts_store.py          # Layer 4：SQLite FTS5 全文索引（BM25 关键词检索，中文逐字分词）
│   ├── retrieval.py          # Layer 4：HybridRetriever（向量 0.7 + BM25 0.3 混合并集）
│   ├── memory_flush.py       # Memory Flush + Compaction（Three-Pass，教学核心）
│   ├── llm_config.py         # LLM 提供商统一配置（DeepSeek / Qwen 切换）
│   ├── heartbeat_parser.py   # HEARTBEAT.md 解析 + 调度/取消意图检测 + 写入
│   ├── scheduler.py          # APScheduler 调度器 + 任务执行 + SSE 广播
│   ├── skill_loader.py       # Skills 技能加载器：SKILL.md 解析 + 关键词匹配 + 渐进式披露
│   ├── task_planner.py       # 任务规划引擎：脚本模式（ScriptExecutor）+ JSON 模式（TaskGraph/TaskExecutor，兼容旧格式）
│   ├── command_executor.py   # 命令执行：安全策略 + shell 命令执行 + [EXEC:] 标记解析（旧格式兼容）
│   ├── agent.py              # CLI 版 Agent（四层记忆 + Skills 技能联动演示）
│   ├── serve.py              # FastAPI + SSE（/chat /flush /stream /reset 等）
│   └── reset.py              # 备份/恢复/出厂重置 CLI 工具
│
├── skills/                   # Skills 技能定义（每个子目录一个技能）
│   ├── flash-card/
│   │   ├── SKILL.md          # 闪卡技能描述（触发词 / 执行流程 / 数据格式）
│   │   ├── data/             # 单词 JSON 数据文件
│   │   └── scripts/
│   │       └── make_flashcard.py  # JSON → HTML 转换脚本
│   └── baoyu-diagram/
│       ├── SKILL.md          # 图表技能描述（设计系统 / 布局规则 / SVG 规范）
│       ├── references/       # 各图表类型参考文档
│       │   ├── architecture.md
│       │   ├── flowchart.md
│       │   ├── sequence.md
│       │   └── structural.md
│       └── scripts/
│           └── main.ts       # SVG → @2x PNG 转换脚本（需 bun）
│
├── memory/                   # Markdown 记忆配置文件（人类可读可编辑）
│   ├── SOUL.md               # Agent 人格定义（手动编辑）
│   ├── USER.md               # 用户画像（Memory Flush 自动更新）
│   ├── MEMORY.md             # 跨会话持久记忆条目（Flush 自动追加）
│   ├── AGENTS.md             # 操作规范 + 能力声明（手动编辑）
│   ├── HEARTBEAT.md          # 定时任务定义（对话意图自动写入 + 手动编辑）
│   └── YYYY-MM-DD.md         # 每日日志（近端记忆，Flush 自动追加，运行时生成）
│
├── data/
│   └── vector_index/         # FAISS 索引（memory.faiss + memory_meta.pkl）
│
├── outputs/
│   ├── sessions/             # SQLite DB（memory.db：sessions + messages + memory_fts）
│   ├── skill_scripts/        # Skills 脚本临时存储（执行后自动清理）
│   └── diagram/              # baoyu-diagram 技能输出目录
│
├── backups/
│   └── initial/              # 出厂初始快照（USER/MEMORY/HEARTBEAT/SOUL/AGENTS.md + 空索引）
│
├── index.html                # Web UI（单文件，无外部 CDN 依赖）
├── requirements.txt
├── ARCHITECTURE.md
├── USAGE_GUIDE.md
└── RESUME_GUIDE.md
