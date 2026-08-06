# skill_optimize 使用指南

## 核心思想

传统的 Skill 进化（Nudge）依赖**测试集**来发现 Skill 的缺陷：
- 需要人工设计测试题
- 评估器判定对错
- 失败样本触发 Reviewer 优化

`skill_optimize` 采用不同的思路：**用户反馈驱动**的 Skill 优化：
- 用户在真实使用中发现问题
- 直接反馈给系统
- 系统自动分析并改进 Skill

```
用户使用 Skill → 产生反馈 → 系统收集分析 → Skill 自动进化
```

## 两种优化模式

### 模式1：离线优化（批量处理）

积累多条反馈后统一优化，适合多用户反馈汇总分析。

```python
from skill_optimize import SkillOptimizeManager

manager = SkillOptimizeManager(skills_dir="skills-origin")

# 收集反馈（多次）
manager.record_feedback("flashcard", "apple", "['苹果']", "缺少使用场景举例")
manager.record_feedback("flashcard", "banana", "['香蕉']", "建议加上英式美式发音")
manager.record_feedback("flashcard", "hello", "['你好']", "格式有点乱")

# 积累够后统一优化
result = manager.run_optimization("flashcard", use_llm=True)
```

### 模式2：在线优化（实时处理）

用户说完立即处理，立即更新 Skill，适合即时生效场景。

```python
manager = SkillOptimizeManager(skills_dir="skills-origin")

# 用户刚生成了一张卡片
card = generate_flashcard("apple")  # ['apple', '苹果']

# 用户说"缺少使用场景举例"
result = manager.process_feedback_now(
    skill_name="flashcard",
    user_input="apple",
    generated_output=str(card),
    feedback_text="缺少使用场景举例，能造个句子吗？",
)

if result["status"] == "updated":
    print("Skill 已更新！下次生成会包含使用场景")
```

### 两种模式对比

| 维度 | 离线优化 | 在线优化 |
|------|---------|---------|
| 处理方式 | 批量积累后统一处理 | 用户说完立即处理 |
| 反馈数量 | 需要 N 条才触发 | 1 条即可触发 |
| 实时性 | 慢（等积累） | 快（即时生效） |
| API 调用 | 少（批量） | 多（实时） |
| 适用场景 | 多用户反馈汇总 | 单人即时优化 |

## 适用场景

| 场景 | 适合用 skill_optimize？ |
|------|----------------------|
| 单词卡片生成 | ✅ 用户会说"缺少例句"、"缺少发音" |
| 图表生成 | ✅ 用户会说"颜色不好看"、"布局太挤" |
| 文案撰写 | ✅ 用户会说"语气太正式"、"不够活泼" |
| 客服对话 | ❌ 测试集更可控，适合 Nudge |
| 数学解题 | ❌ 有明确对错，适合 Nudge |

## 快速开始

### 1. 基础用法：管理器模式

```python
from skill_optimize import SkillOptimizeManager

# 初始化管理器
manager = SkillOptimizeManager(skills_dir="skills-origin")

# 记录用户反馈
manager.record_feedback(
    skill_name="flashcard",
    user_input="apple",
    generated_output="['苹果']",
    feedback_text="缺少使用场景举例，能造个句子吗？",
)

manager.record_feedback(
    skill_name="flashcard",
    user_input="apple",
    generated_output="['苹果']",
    feedback_text="建议加上英式和美式发音的对比",
)

# 运行优化（当反馈数 >= 3 时触发）
result = manager.run_optimization("flashcard", use_llm=True, api_key="sk-...")
print(result)
```

### 2. 快速优化：一条函数搞定

```python
from skill_optimize import quick_optimize
from skill_manager import SkillManager

sm = SkillManager("skills-origin")

result = quick_optimize(
    skill_name="flashcard",
    skill_content=sm.get("flashcard"),
    feedback_list=[
        {"feedback_text": "缺少使用场景举例", "feedback_type": "suggestion"},
        {"feedback_text": "建议加上英式美式发音对比", "feedback_type": "suggestion"},
        {"feedback_text": "格式有点乱", "feedback_type": "complaint"},
    ],
    skill_manager=sm,
    use_llm=False,  # 先用规则分析，不花钱
)

print(result["patterns"])  # 看到识别出的模式
print(result["actions"])  # 看到生成的优化操作
```

### 3. 收集隐式反馈

当用户**修改了生成内容**时，说明原始输出不够好：

```python
# 用户修改了生成结果
manager.record_implicit_feedback(
    skill_name="flashcard",
    user_input="apple",
    original_output="['苹果']",
    revised_output="['苹果', '英:/ˈæpəl/, 美:/ˈæpəl/', '例句: I eat an apple every day']",
)
```

### 4. 收集追问式反馈

当用户追问"能不能加上 XXX"时：

```python
manager.record_from_follow_up(
    skill_name="flashcard",
    user_input="apple",
    generated_output="['苹果']",
    follow_up_text="能不能加上英式和美式发音的对比？",
)
```

## 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│  用户使用阶段                                                │
│                                                             │
│  用户 → Agent(Skill) → 生成结果 → 用户反馈                   │
│         ↑                                                    │
│    Skill 库（可能不完善）                                     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  收集阶段（UserFeedbackCollector）                             │
│                                                             │
│  - 显式反馈：用户说"缺少 XXX"                                 │
│  - 隐式反馈：用户修改了生成内容                                 │
│  - 追问反馈：用户要求"能不能加 XXX"                           │
│                                                             │
│  → 存储到 outputs/user_feedback/{skill}_feedback.json       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  分析阶段（FeedbackAnalyzer）                                 │
│                                                             │
│  反馈文本 → 模式识别 → 聚类统计                               │
│                                                             │
│  预定义类别：                                                │
│  - 缺少使用场景 / 缺少对比 / 缺少语法说明 / 缺少发音信息        │
│  - 格式不清晰 / 内容不准确 / 信息太少 / 重复内容               │
│                                                             │
│  → 输出：[{category, count, examples, suggestion}]            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  优化阶段（SkillOptimizer）                                  │
│                                                             │
│  两种模式：                                                  │
│  1. 规则驱动（RuleBasedOptimizer）- 快/免费/简单              │
│  2. LLM 驱动（SkillOptimizer）- 智能/收费/复杂               │
│                                                             │
│  → 输出：[{action: patch/create, old_text, new_text}]       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  执行阶段（SkillManager）                                    │
│                                                             │
│  - patch：精确替换 Skill 中的指定文本                         │
│  - create：创建新的 Skill 文件                                │
│  - 自动保存版本快照和历史                                     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  验证阶段                                                    │
│                                                             │
│  用户再次使用 → 检验改进效果 → 新的反馈                       │
└─────────────────────────────────────────────────────────────┘
```

## 两种优化器对比

| 特性 | RuleBasedOptimizer | SkillOptimizer (LLM) |
|------|-------------------|---------------------|
| 智能程度 | 简单规则匹配 | 理解上下文 |
| 速度 | 快 | 慢 |
| 成本 | 免费 | API 调用费 |
| 适用场景 | 模式固定的反馈 | 复杂的、需要理解的反馈 |
| 示例 | "缺少使用场景" → 加一行规则 | "总觉得差点意思" → 需要理解意图 |

推荐策略：
1. 先用 RuleBasedOptimizer 跑，捕获高频模式
2. 复杂反馈积累多了，再用 LLMOptimizer 做深度优化

---

## 开发者优化器（DeveloperOptimizer）

除了用户反馈驱动的优化，还有**开发者视角**的优化：从执行效率、Token 消耗等角度分析并优化 Skill。

### 什么时候需要开发者优化？

| 场景 | 说明 |
|------|------|
| Skill 文件太大 | 每次加载消耗大量 token，成本高 |
| 规则太复杂 | 分支过多导致响应慢 |
| 示例冗余 | 过长的示例列表可以压缩 |
| 结构不合理 | 常用规则没有前置 |

### 快速开始

```python
from skill_optimize import DeveloperOptimizer
from skill_manager import SkillManager

sm = SkillManager("skills-origin")
optimizer = DeveloperOptimizer(sm)

# 分析单个 Skill 的效率
analysis = optimizer.analyze_skill("baoyu-diagram")
print(analysis)
# {'skill_name': 'baoyu-diagram', 'metrics': {'token_count': 4500, ...}, 'efficiency_score': '中', 'issues': [...]}

# 分析并自动优化
result = optimizer.analyze_and_optimize("baoyu-diagram", auto_apply=False)
print(result["actions"])  # 查看优化建议
```

### 分析指标

| 指标 | 说明 | 阈值建议 |
|------|------|---------|
| token_count | 估算 token 数 | > 3000 需关注 |
| rule_count | 规则/章节数 | 正常 10-30 |
| branch_count | 条件分支数 | > 15 需优化 |
| list_count | 列表项数 | > 30 需压缩 |
| efficiency_score | 效率评分 | 高/中/低 |

### 开发者优化工作流

```
┌─────────────────────────────────────────────────────────────┐
│  DeveloperOptimizer                                         │
│                                                             │
│  输入：Skill 内容 + 调用统计（可选）                          │
│  ↓                                                         │
│  1. 本地分析：token 数、分支数、列表数                       │
│  2. 问题识别：是否超过阈值                                   │
│  3. 优化生成：                                             │
│     - 问题少 → 规则压缩（免费）                             │
│     - 问题多 → LLM 分析（智能）                             │
│  4. 执行 patch                                              │
└─────────────────────────────────────────────────────────────┘
```

### 分析所有 Skill

```python
# 一次性分析所有 Skill 的效率
all_analysis = optimizer.analyze_all_skills()
for name, result in all_analysis.items():
    if result.get("efficiency_score") != "高":
        print(f"{name}: {result['efficiency_score']} - {result['issues']}")
```

### 与用户优化的区别

| 维度 | 用户优化（SkillOptimizer） | 开发者优化（DeveloperOptimizer） |
|------|-------------------------|-------------------------------|
| 优化目标 | 让生成结果更好（质量） | 让 Skill 消耗更少（效率） |
| 分析角度 | 用户反馈是否满意 | Token 消耗、执行效率 |
| 典型问题 | 缺少使用场景、格式不对 | Skill 太大、分支过多 |
| 触发条件 | 积累 N 条用户反馈 | 手动触发或定时检查 |

两者可以同时使用：
- 用户优化：让 Skill 生成的内容更符合用户期望
- 开发者优化：让 Skill 本身更高效、成本更低

## API 参考

### UserFeedbackCollector

```python
collector = UserFeedbackCollector(storage_dir="outputs/user_feedback")

# 记录反馈
collector.record(skill_name, user_input, generated_output, feedback_text, feedback_type)

# 记录隐式反馈（用户修改了生成内容）
collector.record_from_implicit(skill_name, user_input, original_output, revised_output)

# 记录追问反馈
collector.record_from_follow_up(skill_name, user_input, generated_output, follow_up_text)

# 持久化到磁盘
collector.flush_to_disk(skill_name)

# 读取反馈
feedbacks = collector.get_feedback(skill_name)
```

### FeedbackAnalyzer

```python
analyzer = FeedbackAnalyzer()

# 分析反馈模式
patterns = analyzer.analyze(feedback_list)
# 返回: [FeedbackPattern(category, count, examples, suggestion, skill_section)]

# 获取 top 改进建议
top = analyzer.get_top_improvements(patterns, top_n=3)
```

### SkillOptimizeManager

```python
manager = SkillOptimizeManager(skills_dir="skills-origin")

# 记录反馈
manager.record_feedback(skill_name, user_input, output, feedback_text)

# 运行优化
result = manager.run_optimization(skill_name, use_llm=False, min_feedback_count=3)

# 获取优化摘要
summary = manager.get_optimization_summary(skill_name)
```

### quick_optimize

```python
result = quick_optimize(
    skill_name="flashcard",
    skill_content=skill_md_text,
    feedback_list=[
        {"feedback_text": "缺少使用场景", "feedback_type": "suggestion"},
    ],
    skill_manager=sm,
    use_llm=False,
)
```

## 与 Nudge 的关系

`skill_optimize` 不是要取代 Nudge，而是互补：

| 维度 | Nudge | skill_optimize |
|------|-------|----------------|
| 触发条件 | 测试集失败 | 用户反馈 |
| 反馈类型 | 对/错 | 建议/抱怨/纠正/表扬 |
| 设计成本 | 高（需测试集） | 低（用户直接给） |
| 适用场景 | 评估明确的场景 | 主观/创意类场景 |
| 进化时机 | 块结束时批量 | 可实时 |

可以同时使用：
- Nudge 处理可量化评估的问题（客服对话）
- skill_optimize 处理主观体验类的问题（卡片生成、图表生成）
