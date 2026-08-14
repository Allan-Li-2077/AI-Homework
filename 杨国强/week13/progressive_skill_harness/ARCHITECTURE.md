# ARCHITECTURE.md — Progressive Skill Harness 技术方案

## 一、项目定位

### 与原 `agent_memory_system` 的关系
本项目以 [agent_memory_system](../agent_memory_system/) 为**模板**，复用了它的：
- `llm_config.py`：DeepSeek / Qwen 切换
- `session_db.py`：SQLite 会话历史
- `memory_loader.py`：SOUL/USER/AGENTS/MEMORY.md 加载
- `vector_store.py`：FAISS 向量库
- `fts_store.py`：SQLite FTS5 中文逐字分词
- `retrieval.py`：向量 0.7 + BM25 0.3 混合

并在其上**新增**了 5 个模块，构建"渐进式 Skill 加载"能力。

### 教学场景
本项目回答两个核心问题：
> "ChatGPT 怎么知道该调用哪个工具？"  
> "几十上百个 skill，怎么做到启动成本几乎为零？"

通过一个有 7 个示例 skill 的 AI 助手，学生能亲眼看到：
1. **启动时只读 frontmatter**（约 5KB）—— 全量索引，零正文 IO
2. **用户提问时粗筛 + 精筛**—— 从 N 个 skill 中圈定 K 个候选
3. **真正调用时才读 SKILL.md 正文**—— 占位符替换 → LLM 执行
4. **执行结果写回四层记忆**—— 下次再问"我之前用过哪些 skill"也能召回

---

## 二、六层渐进式加载模型

```
                        用户输入
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ Layer 3 — 长期记忆（全量加载，必读）                            │
│   ├─ SOUL.md      人格                                       │
│   ├─ USER.md      用户画像                                   │
│   ├─ AGENTS.md    操作规范                                   │
│   └─ MEMORY.md    最近 10 条记忆条目                          │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ Layer S0 — Skill 注册表（启动时一次性扫，仅读 frontmatter）    │
│   skills/*/SKILL.md  →  解析 frontmatter → SkillMeta 字典    │
│   启动成本 ≈ 5KB frontmatter + 0 字节正文                     │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ Layer S1 — Skill 选择（按需，零 IO）                          │
│   Step 1: keyword/trigger 粗筛 → 候选 ≤ 6 个（零 LLM）        │
│   Step 2: LLM 看 ~500 字符 description → 决策 JSON           │
│   action: skill_call / direct_answer / chain                 │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼（决策命中 skill）
┌──────────────────────────────────────────────────────────────┐
│ Layer S2 — Skill 加载（按需，真正读 SKILL.md 全文）           │
│   SkillLoader.load(name, params)                              │
│   - 缓存命中：直接返回                                        │
│   - 缓存未中：读文件 + 替换 {{占位符}} → SkillContract         │
└──────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────────┐
│ Layer 4        │ │ Layer S3       │ │ Layer S3           │
│ 混合检索       │ │ Skill 执行     │ │ Skill 执行         │
│ FAISS + BM25   │ │ prompt 型      │ │ code / workflow 型 │
└────────────────┘ └────────────────┘ └────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ Layer S4 — 记忆写入（自动）                                   │
│   SkillRecorder.record_call()                                 │
│   → USER.md (用过的 Skills 列表)                              │
│   → MEMORY.md (skill_call 类条目)                             │
│   → FAISS (向量化)                                            │
│   → FTS5 (关键词索引)                                         │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ 最终组装 Context Window                                       │
│   system_prompt = layer3 + skill_results + memory_snippets    │
│   → LLM 流式生成回答                                          │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、为什么"渐进"？

### 启动成本对比

| 方案 | N=10 个 skill 时 | N=100 个 skill 时 | N=1000 个 skill 时 |
|------|------------------|-------------------|--------------------|
| **全量加载正文**（每次启动）| ~200 KB | ~2 MB | ~20 MB |
| **本项目**（仅读 frontmatter）| ~5 KB | ~50 KB | ~500 KB |

frontmatter 平均每个 ~500 字节（name + desc + keywords + triggers），正文平均每个 ~20 KB。

### 调用成本对比

| 方案 | 每次对话 LLM 看到的 token |
|------|--------------------------|
| 把所有 skill 正文都拼进 prompt | O(N) × 20KB → 100K+ tokens |
| **本项目**（仅命中 skill 的正文） | O(K) × 20KB → K 通常 ≤ 2 |

**核心收益**：当 skill 数量增长到 100+ 时，启动几乎零成本，每次对话的 LLM 调用也只看到真正用到的 skill 描述。

---

## 四、SKILL.md 格式规范

```markdown
---
name: translate                # 必填，skill 标识
version: 1.0.0                 # 语义化版本
description: ...               # LLM 看的描述，决定能否被粗筛命中
keywords: [翻译, translate]    # 用于 keyword 粗筛
triggers: [translation_request] # 触发场景标签
execution: prompt              # prompt | code | workflow
parameters:                    # 可选：参数 schema
  - name: text
    type: string
    required: true
    description: 原文文本
enabled: true                  # 默认 true，false = 禁用
---

# Skill 正文（仅在调用时加载）

你是翻译助手 ...

## 任务
将 `{{text}}` 翻译成 `{{target_lang}}` ...

## 注意事项
...
```

### execution 三种模式

| 模式 | 说明 | 配套文件 | 适用场景 |
|------|------|---------|---------|
| `prompt` | 把正文作为 system prompt 调 LLM | 无 | 翻译、总结、问答等"靠 LLM 脑子"的任务 |
| `code` | 用 sandbox 执行 code.py | `code.py` | 文件读取、shell 命令、数据处理等"靠代码"的任务 |
| `workflow` | 按 workflow.yaml 串行调用子 skill | `workflow.yaml` | 多步骤研究、复合任务 |

---

## 五、各模块设计要点

### `skill_registry.py` — Layer S0
- **只读 frontmatter**：`_FRONT_MATTER_RE` 正则提取 `---\n...\n---` 块
- **零正文 IO**：`_parse_front_matter` 解析完成后立刻丢弃 body
- **缓存**：单例 `get_registry()`，避免重复扫描
- **粗筛能力**：`search_by_keyword()` 对 description/keywords/triggers 做子串匹配

### `skill_selector.py` — Layer S1
- **两层筛选**：先 `search_by_keyword`（零 LLM），再 LLM 看候选目录（~500 字符）
- **决策 JSON**：`{action, skills, confidence, ...}` 让 LLM 学会用工具
- **降级**：LLM 调用失败 → 直接走 `direct_answer`，绝不崩溃

### `skill_loader.py` — Layer S2
- **占位符替换**：`{{param}}` 用 `_PLACEHOLDER_RE` 替换
- **缓存**：key = `name::md5(params)`，同参复用
- **缺失参数**：未提供且 required=True → 记录到 `params_missing`，标 `<<MISSING>>`

### `skill_executor.py` — Layer S3
- **三种 execution**：
  - `prompt`：正文 → system prompt → LLM 流式
  - `code`：动态 import code.py，注入 sandbox API
  - `workflow`：yaml.safe_load + 串行调用
- **sandbox 限制**（code 型）：
  - shell 命令白名单：`echo/ls/dir/cat/type/find/where/python`
  - 路径白名单：仅当前目录及其父目录
  - 文件类型白名单：仅文本类
- **broadcast 回调**：执行过程中实时推事件给前端

### `skill_recorder.py` — Layer S4
- **复用原项目的写入路径**：`MEMORY.md` 的 `<!-- MEMORY_ENTRIES_END -->` marker
- **追加到四层索引**：`USER.md` 加 skill 列表 / `MEMORY.md` 加条目 / FAISS 向量化 / FTS5 索引
- **降级**：写失败不阻塞主流程

---

## 六、示例 Skill 清单

| skill | execution | 用途 |
|-------|-----------|------|
| `translate` | prompt | 多语言翻译 |
| `summarize` | prompt | 长文本/会议纪要摘要 |
| `code_review` | prompt | 代码审查 |
| `math_solver` | prompt | 数学题详解 |
| `web_search` | prompt | 联网搜索（演示版，未接真实 API）|
| `file_reader` | code | 读取本地文本文件（sandbox 安全）|
| `research_workflow` | workflow | web_search → summarize 串联 |

---

## 七、目录结构

```
progressive_skill_harness/
├── src/
│   ├── llm_config.py          # 复用：LLM 切换
│   ├── session_db.py          # 复用：SQLite 会话
│   ├── memory_loader.py       # 复用：长期记忆加载
│   ├── vector_store.py        # 复用：FAISS 向量
│   ├── fts_store.py           # 复用：FTS5 关键词
│   ├── retrieval.py           # 复用：混合检索
│   │
│   ├── skill_registry.py      # 新增：S0 注册表
│   ├── skill_selector.py      # 新增：S1 选择器
│   ├── skill_loader.py        # 新增：S2 加载器
│   ├── skill_executor.py      # 新增：S3 执行器
│   ├── skill_recorder.py      # 新增：S4 记录器
│   ├── progressive_agent.py   # 新增：主循环
│   ├── progressive_serve.py   # 新增：FastAPI + SSE
│   └── reset_cli.py           # 新增：CLI 重置工具
│
├── skills/                    # 新增：Skill 目录
│   ├── translate/SKILL.md
│   ├── summarize/SKILL.md
│   ├── code_review/SKILL.md
│   ├── math_solver/SKILL.md
│   ├── web_search/SKILL.md
│   ├── file_reader/SKILL.md
│   │   └── code.py            # execution=code 配套
│   └── research_workflow/
│       ├── SKILL.md
│       └── workflow.yaml      # execution=workflow 配套
│
├── memory/                    # 与原项目相同的 4 个 md
│   ├── SOUL.md
│   ├── USER.md
│   ├── MEMORY.md
│   └── AGENTS.md
│
├── data/vector_index/         # FAISS 索引
├── outputs/sessions/          # SQLite
├── backups/initial/memory/    # 出厂快照
│
├── index.html                 # Web UI（六层可视化）
├── requirements.txt
├── setup_env.ps1
├── start.ps1
├── reset_cli.py               # CLI 备份/恢复
├── run_smoke_test.py          # 不依赖 LLM 的冒烟测试
├── ARCHITECTURE.md
└── USAGE_GUIDE.md
```

---

## 八、关键工程决策

| 决策 | 取舍 |
|------|------|
| Frontmatter 必填 `name` | 放弃自定义标识 → 换取注册表的简单性 |
| 占位符语法 `{{key}}` 而非 `{{ key }}` | 接受无空格变体 → 减少 typo |
| LLM 精筛只看元数据目录（不读正文） | 候选 ≤ 6 个时 token 可控 |
| code 型 sandbox 不允许任意 subprocess | 安全优先 → 部分场景需改写 |
| workflow 类型支持 `$user_query` 模板替换 | 简化 yaml 配置 → 仅支持单变量 |
| SkillRecorder 写入失败不抛异常 | 主流程优先 → 用户可能感觉"调用了但没记住" |

---

## 九、可扩展方向

1. **多模态 Skill**：增加 `execution=vision`，上传图片给 LLM
2. **异步 Skill**：增加 `execution=async`，触发后台任务
3. **Skill Marketplace**：从远程仓库（GitHub / S3）下载 SKILL.md
4. **跨 Skill 状态共享**：在 SkillContract 中增加 `shared_state` 字段
5. **Skill 版本管理**：在 frontmatter 中支持 `requires: [translate>=2.0]`