# USAGE_GUIDE.md — 渐进式加载 Skill Harness 使用指导

## 一、环境准备

### 安装依赖

```bash
pip install openai>=1.0.0
```

### 配置 API Key

```bash
# 使用 DeepSeek（默认，推荐）
export DEEPSEEK_API_KEY=sk-xxxxxxxx

# 或使用 Qwen/DashScope
export LLM_PROVIDER=qwen
export DASHSCOPE_API_KEY=sk-xxxxxxxx
```

---

## 二、快速启动

### CLI 交互模式

```bash
cd skill_harness/
python cli.py
```

启动后将看到：

```
╔══════════════════════════════════════════════════════╗
║          渐进式 Skill Harness — CLI 演示              ║
╚══════════════════════════════════════════════════════╝

  本工具演示渐进式加载 Skills 的完整流程：
  L0 注册表扫描 → L1 意图匹配 → L2 渐进加载 → L3 按需引用
  未匹配的 skill 零 I/O 开销，参考文件仅在明确引用时读取

── Phase 0 (L0): 启动扫描 — 仅读取 frontmatter ──
  ✓ 发现 2 个技能（耗时 0.78ms）
    baoyu-diagram v1.117.3
    创建专业的暗色主题 SVG 图表...
    flash-card
    为一个英语单词生成静态 HTML 学习闪卡...

  命令: /skills | /load <name> | /ref <skill> <ref> | /stats | /help | /exit
```

---

## 三、CLI 命令参考

### 📋 `/skills` — 查看可用技能

列出 L0 阶段发现的所有技能（仅名称和描述，正文未加载）。

```
你：/skills

═══ 已发现技能 (L0 注册表) ═══
  baoyu-diagram v1.117.3
  创建专业的暗色主题 SVG 图表...
  flash-card
  为一个英语单词生成静态 HTML 学习闪卡...
```

### 📖 `/load <name>` — 手动加载技能 (L2)

强制加载某个技能的完整指令，即使未被匹配。

```
你：/load baoyu-diagram

── Phase 2 (L2): 手动加载: baoyu-diagram ──
  ✓ 已加载: baoyu-diagram
  指令: 7521 字符
  参考: 4 个
  脚本: 1 个
  耗时: 0.77ms
```

### 📄 `/ref <skill> <ref>` — 按需加载参考文件 (L3)

演示参考文件的延迟加载。只有显式请求时才从磁盘读取。

```
你：/ref baoyu-diagram architecture

── Phase 3 (L3): 按需加载参考: architecture → baoyu-diagram ──
  ✓ 已加载: architecture.md (1741 字符, 0.5ms)
```

### 📊 `/stats` — 查看运行统计

```
═══ Harness 运行统计 ═══
  discovered_skills: 2
  loaded_skills: 1       ← 只有 1 个被加载
  references_loaded: 2   ← 只有 2 个被读取
  total_io_kb: 9.0
```

### ❓ `/help` — 帮助

### 🚪 `/exit` — 退出

---

## 四、自然语言交互

直接输入自然语言，Harness 自动匹配并加载对应 Skill：

```
你：帮我画一个用户登录的流程图

── Phase 1 (L1): 意图匹配 ──
  ✓ #1 baoyu-diagram (keyword, 62%)
    命中关键词: 流程, 流程图, 程图

── Phase 2 (L2): 渐进加载: baoyu-diagram ──
  指令长度: 7521 字符
  参考文件: 4 个
    📄 architecture.md [未加载]
    📄 flowchart.md [未加载]
    📄 sequence.md [未加载]
    📄 structural.md [未加载]
  加载耗时: 0.77ms

── Context: 上下文组装 ──
  上下文长度: 7862 字符

── LLM: 尝试 LLM 执行... ──
Muse：好的，我来为你创建一个用户登录流程图...
```

注意：**4 个参考文件状态都是"未加载"**，它们只有在你明确触发 `/ref` 或 Skill 执行流程引用它们时才会被读取。

---

## 五、编程接口

### 作为库使用

```python
from pathlib import Path
from skill_harness import SkillHarness

# 初始化
harness = SkillHarness(skills_dirs=[Path("./skills")])
harness.startup()  # L0

# 完整流水线
result = harness.process("画个架构图")
print(result["matches"])       # 匹配结果
print(result["loaded_skills"]) # 加载的 Skill
print(result["context"])       # 可注入 LLM 的上下文

# L3 按需加载
ref = harness.load_reference("baoyu-diagram", "architecture")

# LLM 执行
response = harness.run_with_llm(result["context"])
```

### 分步调用

```python
from skill_harness import SkillRegistry, SkillLoader, SkillMatcher

# L0: 注册
reg = SkillRegistry()
reg.discover([Path("./skills")])

# L1: 匹配
matcher = SkillMatcher(reg)
matches = matcher.match("画个图")

# L2: 加载
loader = SkillLoader()
skill = loader.load_skill(matches[0].skill.meta)  # 此时才读正文

# L3: 按需
ref_content = loader.load_reference(skill, "architecture")
```

---

## 六、添加新 Skill

在 `skills/` 目录下创建新目录，放入一个 `SKILL.md` 文件：

```
skills/
└── my-skill/
    └── SKILL.md
```

`SKILL.md` 格式：

```markdown
---
name: my-skill
description: 这是一个示例技能，当用户说"示例"或"测试"时触发
version: 1.0.0
---

# 我的技能

## 触发场景
- 用户说"帮我做个示例"
- 用户说"测试一下"

## 执行流程
1. 理解用户需求
2. 生成结果
3. 返回给用户
```

可选目录：
- `references/` — 放参考文件（.md），由 L3 按需加载
- `scripts/` — 放可执行脚本（.py / .ts / .sh），由 L4 按需执行
- `data/` — 放数据文件（.json），由脚本使用

**新增 Skill 后无需重启**，Harness 每次启动时自动扫描。

---

## 七、验证渐进式加载

### 验证 L0（仅读 frontmatter）

观察启动日志：发现 N 个 skill，耗时 < 5ms。所有 skill 的指令正文都未加载。

### 验证 L2（只加载匹配的）

```
你：画个架构图          → baoyu-diagram 被加载，flash-card 不加载
你：/stats              → loaded_skills: 1
你：做个单词闪卡         → flash-card 被加载
你：/stats              → loaded_skills: 2
```

### 验证 L3（按需加载）

```
你：/ref baoyu-diagram architecture    → 加载了 architecture.md
你：/ref baoyu-diagram flowchart       → 加载了 flowchart.md
你：/stats                              → references_loaded: 2
```

### 验证零开销

```
你：今天天气真好
→ Phase 1 (L1): 未匹配到任何技能
→ loaded_skills: 0
→ 零 I/O
```

---

## 八、常见问题

**Q: L0 扫描会随着 skill 增加变慢吗？**

A: L0 只读每个 SKILL.md 的前 ~15 行（frontmatter），不读正文。即使有 50 个 skill，每个 skill 的 "扫描" 最多 500 字节，总计 25KB，约 5-15ms。对比全量加载 50 个 × 平均 5000 字 = 250KB，差距约 10 倍。

**Q: 中文关键词匹配为什么不用 jieba 分词？**

A: 零依赖原则。skill frontmatter 的描述通常较短（50-200 字），中文 n-gram（2-4 字滑动窗口）对短查询的覆盖率和召回率已经足够。如果应用场景需要长篇中文文档匹配，可以替换为 jieba。

**Q: 如果用户输入同时匹配多个 skill 怎么办？**

A: Harness 按匹配得分降序返回 top_k（默认 3）。Phase 2 只会加载得分 ≥ 阈值(0.2) 的 skill。用户也可以手动 `/load <name>` 选择。

**Q: LLM 不可用时怎么办？**

A: L1 的命令匹配和关键词匹配不依赖 LLM，仍然可以正常工作。只有 Tier 3（LLM 语义匹配）和 LLM 执行会降级跳过，Harness 本身不受影响。
