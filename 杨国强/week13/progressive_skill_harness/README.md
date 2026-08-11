# Progressive Skill Harness

> 以 [agent_memory_system](../agent_memory_system/) 为模板，**实现"渐进式 Skill 加载"能力**的 Harness。
>
> 解决两个核心问题：
> 1. 几十上百个 skill，**启动成本几乎为零**
> 2. 每次对话，LLM 看到的 prompt 只包含**真正用到的** skill 正文

---

## 🚀 快速开始

```powershell
# 1. 首次安装 + 配置 API Key
.\setup_env.ps1

# 2. 启动 Web 版（推荐）
.\start.ps1 web
# 浏览器访问 http://localhost:8000

# 或 CLI 版
.\start.ps1 cli

# 不依赖 LLM 的冒烟测试
.\start.ps1 smoke
```

## 🧩 核心特性

### 六层渐进式加载模型

| Layer | 名称 | 加载时机 | 加载成本 |
|-------|------|---------|---------|
| **3** | 长期记忆（SOUL/USER/AGENTS/MEMORY.md）| 每轮对话 | 全量 |
| **S0** | Skill 注册表 | **启动时一次性** | 仅 frontmatter（~3.5KB / 7 个 skill）|
| **S1** | Skill 选择 | 每轮对话 | keyword 粗筛（零 LLM）+ LLM 精筛（~500 字符）|
| **S2** | Skill 加载 | **按需**，决策命中时 | 读 SKILL.md 正文（~1KB）+ 占位符替换 |
| **L4** | 混合检索 | 每轮对话 | FAISS + BM25 |
| **S3** | Skill 执行 | 按需 | prompt / code / workflow 三种模式 |
| **S4** | 记忆写入 | 调用完成后 | USER.md / MEMORY.md / FAISS / FTS5 |

### 启动成本对比

```
7 个 skill 的实测数据（来自冒烟测试）：
  frontmatter 总计：3,518 字符（约 3.5 KB）
  正文待按需加载：5,087 字符（约 5 KB）
  启动时实际加载：仅 frontmatter（节省 59% IO）
```

### 三种 Execution 模式

| 模式 | 配套文件 | 示例 |
|------|---------|------|
| `prompt` | 无 | translate / summarize / code_review / math_solver / web_search |
| `code` | `code.py` | file_reader（沙箱执行，文件读取 + 白名单 shell）|
| `workflow` | `workflow.yaml` | research_workflow（web_search → summarize 串联）|

## 📁 项目结构

```
progressive_skill_harness/
├── src/
│   ├── llm_config.py        ← 复用自原项目
│   ├── session_db.py        ← 复用
│   ├── memory_loader.py     ← 复用
│   ├── vector_store.py      ← 复用
│   ├── fts_store.py         ← 复用
│   ├── retrieval.py         ← 复用
│   │
│   ├── skill_registry.py    ★ S0：仅读 frontmatter
│   ├── skill_selector.py    ★ S1：keyword 粗筛 + LLM 精筛
│   ├── skill_loader.py      ★ S2：按需读正文 + 占位符替换 + 缓存
│   ├── skill_executor.py    ★ S3：prompt/code/workflow 三种执行模式
│   ├── skill_recorder.py    ★ S4：调用记录写回四层记忆
│   ├── progressive_agent.py ★ 主循环：六层编排
│   ├── progressive_serve.py ★ FastAPI + SSE
│   └── reset_cli.py         ← CLI 重置工具
│
├── skills/                  ★ 示例 Skills（7 个，覆盖三种 execution）
│   ├── translate/  summarize/  code_review/  math_solver/
│   ├── web_search/  file_reader/ (code.py)  research_workflow/ (workflow.yaml)
│
├── memory/                  ← 与原项目相同：SOUL/USER/MEMORY/AGENTS.md
├── data/vector_index/       ← FAISS 索引
├── outputs/sessions/        ← SQLite
├── backups/initial/         ← 出厂快照
│
├── index.html               ← 单文件前端（SSE 实时展示六层加载）
├── ARCHITECTURE.md          ← 详细技术方案
├── USAGE_GUIDE.md           ← 使用指南
└── requirements.txt
```

## 🎯 设计哲学

1. **复用而非重写**：记忆系统（llm_config/session_db/memory_loader/vector_store/fts_store/retrieval）从原项目**直接拷贝**，未做修改
2. **新增而非改造**：渐进式加载作为**新能力**叠加，原有功能完全保留
3. **Markdown 即配置**：每个 skill 是一个目录 + 一个 SKILL.md，零额外 schema
4. **渐进而非全量**：启动成本 O(N × frontmatter)，调用成本 O(K × body)，N >> K

## 🧪 冒烟测试

```
.\start.ps1 smoke
```

输出验证：
- ✅ 7 个 skill 全部正确索引
- ✅ 启动成本仅 3.5 KB frontmatter
- ✅ 占位符 `{{text}}` `{{target_lang}}` 正确替换
- ✅ 缓存机制（同参二次加载命中）
- ✅ 三种 execution 都能加载
- ✅ code 型 skill 在 sandbox 中成功读取文件

## 📚 更多文档

- [ARCHITECTURE.md](ARCHITECTURE.md) — 详细技术方案、模块设计、工程决策
- [USAGE_GUIDE.md](USAGE_GUIDE.md) — 使用指南、自定义 Skill 教程、调试技巧