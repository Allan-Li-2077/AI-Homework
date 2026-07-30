# ARCHITECTURE.md — 渐进式加载 Skill Harness 技术方案

## 一、项目定位

### 教学场景
本项目演示 **如何构建一套支持渐进式加载执行的 Skills Harness**，回答几个核心问题：
> "AI 助手有很多技能，但每次只用一个，为什么要把所有技能的指令全塞进 Context？"
> "如何在有大量 Skills 的情况下保持启动速度？"
> "怎样让未使用的技能零开销？"

通过这个 Harness，学生能亲眼看到：
1. L0 启动时只扫描 SKILL.md 的 frontmatter（名称+描述），不读正文
2. L1 用户输入到来时才做意图匹配
3. L2 只有匹配到的 Skill 才加载完整指令
4. L3 参考文件仅在技能指令明确引用时才从磁盘读取
5. 未匹配的技能零 I/O 开销

### 对照：传统全量加载 vs 渐进式加载

| 维度 | 全量加载 | 渐进式加载 |
|------|---------|-----------|
| 启动时 I/O | 读取所有 SKILL.md + 所有 references | 仅读取 frontmatter（~200 字节/skill） |
| 匹配时 I/O | 无（已全在内存） | 读取 1 个 SKILL.md 正文 |
| 未匹配技能 | 白白占用内存，增加 Context 噪音 | 零开销 |
| 适用场景 | 技能少（≤3 个） | 技能多（≥5 个），指令长（数千字） |
| 类比例子 | 把所有工具摊在桌上 | 工具箱，用到哪个拿哪个 |

---

## 二、渐进式加载的四个层级

```
用户输入到来
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  L0 注册表扫描（启动时，仅一次）                                │
│                                                             │
│  skills/baoyu-diagram/SKILL.md  → 仅读头部 frontmatter        │
│    name: baoyu-diagram                                       │
│    description: 创建专业的暗色主题 SVG 图表...                  │
│    version: 1.117.3                                          │
│                                                             │
│  skills/flash-card/SKILL.md     → 仅读头部 frontmatter        │
│    name: flash-card                                          │
│    description: 为一个英语单词生成静态 HTML 学习闪卡...          │
│                                                             │
│  耗时: ~1-3ms（与 skill 数量成正比，与正文长度无关）              │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  L1 意图匹配（每次用户输入）                                    │
│                                                             │
│  三层策略（自动逐级升级）：                                      │
│    Tier 1 — 命令匹配: 检测 /skill-name 格式 (0ms)             │
│    Tier 2 — 关键词匹配: 中文 2-4 gram + 英文分词 (~1ms)        │
│    Tier 3 — LLM 语义匹配: 仅在 Tier1/2 无法确定时 (~500ms)     │
│                                                             │
│  "画个架构图" → 关键词[架构图]+[画个] → baoyu-diagram (62%)   │
│  "做个flashcard" → 名称匹配[flashcard≈flash-card] → flash-card │
│  "天气怎么样" → 无匹配 → 零 I/O                                │
└─────────────────────────────────────────────────────────────┘
    │ 匹配成功 ▼
┌─────────────────────────────────────────────────────────────┐
│  L2 渐进加载 — 此时才读取 SKILL.md 完整正文                     │
│                                                             │
│  baoyu-diagram/SKILL.md:                                    │
│    指令正文: 7521 字符（249 行）    ← 此时才读                 │
│    发现 references/: 4 个文件      ← 记路径，不读内容           │
│    发现 scripts/: 1 个文件          ← 记路径，不执行           │
│                                                             │
│  未匹配的 flash-card: 仍然零 I/O                               │
└─────────────────────────────────────────────────────────────┘
    │ Skill 指令执行中 ▼
┌─────────────────────────────────────────────────────────────┐
│  L3 按需加载 — Skill 指令引用 references/ 或 scripts/          │
│                                                             │
│  baoyu-diagram 指令中写道:                                    │
│    "→ 阅读 {baseDir}/references/architecture.md"            │
│    → 触发 load_reference("baoyu-diagram", "architecture")    │
│    → 1741 字符从磁盘读取到内存                                  │
│                                                             │
│  4 个 references 中只有实际引用的被加载，其余保持空              │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、核心数据结构

```
SkillMeta (L0 产物)
├── name: str              # "baoyu-diagram"
├── description: str       # 用于匹配的触发描述
├── version: str           # "1.117.3"
└── path: Path             # 技能目录路径

        │ L2 按需加载
        ▼

Skill (L1+L2 产物)
├── meta: SkillMeta
├── instructions: str      # SKILL.md 去除 frontmatter 的正文
├── references: dict       # {文件名: 内容}，初始全部为空字符串
│   ├── "architecture.md": ""    ← 按需填充
│   ├── "flowchart.md":    ""    ← 按需填充
│   ├── "sequence.md":     ""    ← 按需填充
│   └── "structural.md":   ""    ← 按需填充
└── scripts: list[Path]    # 脚本路径列表
    └── "main.ts"

        │ L3 按需加载
        ▼

skill.references["architecture.md"] = "1741 字符的完整内容..."
skill.references["flowchart.md"]    = "1261 字符的完整内容..."
# sequence.md 和 structural.md 仍未加载
```

---

## 四、模块架构

```
┌─────────────────────────────────────────────────────────┐
│                     cli.py (CLI 入口)                     │
│  交互循环: 匹配 → 加载 → 组装上下文 → LLM 执行                │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  harness.py (主编排器)                     │
│  门面模式，串联三个核心组件:                                 │
│    process(user_input) → MatchResult + context           │
│    build_context(skills) → 可注入 LLM 的文本                │
│    load_reference(name, ref) → L3 按需加载                 │
└──┬───────────────────┬───────────────────┬──────────────┘
   │                   │                   │
┌──▼──────────┐  ┌─────▼────────┐  ┌──────▼──────────┐
│ registry.py │  │  matcher.py  │  │   loader.py     │
│             │  │              │  │                 │
│ L0 注册表    │  │ L1 意图匹配   │  │ L2/L3 渐进加载   │
│             │  │              │  │                 │
│ discover()  │  │ match()      │  │ load_skill()    │
│ list_skills│  │ _match_cmd() │  │ load_reference()│
│ get(name)   │  │ _match_kw()  │  │ list_scripts()  │
│             │  │ _match_llm() │  │                 │
└──────┬──────┘  └──────┬───────┘  └────────┬────────┘
       │                │                    │
       ▼                ▼                    ▼
┌─────────────────────────────────────────────────────────┐
│                   models.py (数据层)                       │
│  SkillMeta  |  Skill  |  MatchResult                     │
└─────────────────────────────────────────────────────────┘
```

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `models.py` | 定义 SkillMeta / Skill / MatchResult 三个核心数据结构 | — | dataclass |
| `registry.py` | L0：扫描 skills/ 目录下的 SKILL.md，仅解析 frontmatter | 目录路径列表 | `dict[name, SkillMeta]` |
| `matcher.py` | L1：三层意图匹配（命令→关键词→LLM） | 用户输入字符串 | `list[MatchResult]` |
| `loader.py` | L2/L3：渐进式加载 SKILL.md 正文 + 按需加载 references | SkillMeta / ref_name | `Skill`（含指令+参考内容） |
| `harness.py` | 主编排器，串联整个流水线并组装可注入 LLM 的上下文 | 用户输入 | `dict`（含匹配/加载/上下文/耗时） |
| `llm_config.py` | LLM 配置，支持 DeepSeek(默认)/Qwen | — | `(OpenAI client, model_name)` |
| `cli.py` | CLI 交互式演示，可视化每个 Phase | — | 终端交互 |

---

## 五、意图匹配算法

### Tier 1: 命令匹配（零成本）

```
用户输入: "/baoyu-diagram 帮我画图"
正则: ^/(\w[\w-]*)
提取: "baoyu-diagram"
查找: registry.get("baoyu-diagram")
结果: MatchResult(score=1.0, type="command")
```

### Tier 2: 关键词匹配（~1ms）

流程：
1. 用户输入 → 中英文关键词提取
   - 中文：2-gram + 3-gram + 4-gram 滑动窗口（不引入 jieba 等分词库）
   - 例如 "画个架构图" → {"画个", "个架", "架构", "构图", "画个架", "个架构", "架构图"}
   - 英文：按非字母数字字符分词
2. 对每个 Skill 的 `name + description` 做同样的关键词提取
3. 计算覆盖率得分: `recall * 0.8 + precision * 0.05 + name_bonus`
   - recall = |交集| / |用户关键词|（用户说了什么被命中）
   - name_bonus: 名称精确匹配 +0.3，去连字符匹配 +0.25，部分匹配 +0.15
4. 得分 ≥ 阈值(0.2) → 返回匹配

**为什么用 n-gram 而不是 jieba 分词？**
- 零依赖。jieba 需要额外安装，且词典文件较大（~5MB）
- n-gram 对短查询足够有效（查询通常 5~15 字）
- 覆盖率比精确分词更宽容（"架构图" 命中 "架构"、"构图"、"架构图" 三个 token）

### Tier 3: LLM 语义匹配（~500ms）

仅在 Tier 1/2 无法确定时触发。将所有 Skill 的 name + description 发给 LLM，由 LLM 判断最匹配的 Skill。

---

## 六、LLM 提供商配置

所有 LLM 调用通过 `llm_config.py` 统一管理，由环境变量 `LLM_PROVIDER` 切换。

| 提供商 | 模型 | 环境变量 | 默认 |
|--------|------|---------|------|
| DeepSeek | `deepseek-chat` | `DEEPSEEK_API_KEY` | ✅ |
| DashScope | `qwen-plus` | `DASHSCOPE_API_KEY` | 备选 |

配置方式：
```bash
# 使用 DeepSeek（默认）
export DEEPSEEK_API_KEY=sk-xxx

# 或切换到 Qwen
export LLM_PROVIDER=qwen
export DASHSCOPE_API_KEY=sk-xxx
```

---

## 七、关键设计决策

| 决策 | 理由 |
|------|------|
| **不依赖 pyyaml** | skill 的 frontmatter 只有 3 个简单字段，手写解析 30 行代码即可，减少依赖 |
| **中文 n-gram 分词** | 零依赖方案，对短查询足够有效，覆盖率比 jieba 更宽容 |
| **去连字符名称匹配** | "flashcard" 应能匹配 "flash-card"，提升容错性 |
| **LLM 匹配仅做 fallback** | 三层渐进：命令(0ms) → 关键词(1ms) → LLM(500ms)，何时用贵的何时用便宜的 |
| **references 初始化为空字符串** | 仅记文件名和路径，不读内容。对比"目录扫描时全读"的方案，节省了大量 I/O |
| **独立 llm_config.py** | 完整复制了 agent_memory_system 的 LLM 配置逻辑，但作为独立模块，不依赖外部项目 |
| **Skill 缓存机制** | 同一 skill 加载后缓存在 loader._cache，后续请求零 I/O |

---

## 八、目录结构

```
作业提交目录/
├── skill_harness/                 # Harness 主体
│   ├── __init__.py                # 包导出 + 版本信息
│   ├── models.py                  # 数据模型 (SkillMeta, Skill, MatchResult)
│   ├── registry.py                # L0 注册表 (90 行)
│   ├── loader.py                  # L1/L2/L3 渐进式加载器 (140 行)
│   ├── matcher.py                 # 三层意图匹配 (180 行)
│   ├── harness.py                 # 主编排器 (140 行)
│   ├── llm_config.py              # LLM 配置 (70 行)
│   └── cli.py                     # CLI 交互演示 (200 行)
│
├── skills/                        # 技能定义目录
│   ├── baoyu-diagram/
│   │   ├── SKILL.md               # 技能主定义（YAML frontmatter + Markdown 指令）
│   │   └── references/            # 参考文件（按需加载）
│   │       ├── architecture.md
│   │       ├── flowchart.md
│   │       ├── sequence.md
│   │       └── structural.md
│   └── flash-card/
│       ├── SKILL.md
│       ├── scripts/               # 可执行脚本（按需执行）
│       │   └── make_flashcard.py
│       └── data/
│           ├── crazy.json
│           ├── resilient.json
│           └── thrill.json
│
├── requirements.txt               # 依赖: openai>=1.0.0
├── ARCHITECTURE.md                # 本文档
└── USAGE_GUIDE.md                 # 使用指导
```
