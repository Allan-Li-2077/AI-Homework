# 读取元数据
(base) PS E:\ai\week13harness和skills\week13 skills和harness> python -m skill_harness.cli list
<frozen runpy>:128: RuntimeWarning: 'skill_harness.cli' found in sys.modules after import of package 'skill_harness', but prior to execution of 'skill_harness.cli'; this may result in unpredictable behaviour
[stage 0] 只读取元数据，发现 2 个 skills
- baoyu-diagram v1.117.3 (295 个 frontmatter 字符)
  创建专业的暗色主题 SVG 图表，支持任意类型——架构图、流程图、时序图、结构图、思维导图、时间线、概念示意图等。当用户要求任何类型的技术或概念图表、系统/流程/数据流可视化、组件关系、网络拓扑、决策树、组织架构图、状态机，或任何结构...
- flash-card (235 个 frontmatter 字符)
  为一个英语单词生成静态 HTML 学习闪卡（含音标、词性、释义、3 条中英对照例句、近义词）。 Use when the user asks to make a flash card / 闪卡 for an English word,...

# 验证先匹配，再加载
(base) PS E:\ai\week13harness和skills\week13 skills和harness> python -m skill_harness.cli match "给我做 crazy 的 flash card"
<frozen runpy>:128: RuntimeWarning: 'skill_harness.cli' found in sys.modules after import of package 'skill_harness', but prior to execution of 'skill_harness.cli'; this may result in unpredictable behaviour
[stage 0] 只读取元数据，发现 2 个 skills
1. flash-card score=16.469 reasons=crazy, flash, card, flash-card keyword
2. baoyu-diagram score=0.709

# 验证只加载被选中的 skill
(base) PS E:\ai\week13harness和skills\week13 skills和harness> python -m skill_harness.cli run "给我做 crazy 的 flash card"
<frozen runpy>:128: RuntimeWarning: 'skill_harness.cli' found in sys.modules after import of package 'skill_harness', but prior to execution of 'skill_harness.cli'; this may result in unpredictable behaviour
stage 0: 只读取元数据，发现 2 个 skills
stage 0: matcher 选中 flash-card (score=16.469, reasons=crazy, flash, card, flash-card keyword)
stage 1: 已加载 SKILL.md (1790 chars, 约 447 tokens)
stage 2: 未加载引用文件
stage 3: 执行适配器 FlashCardRunner
结果: ok - 已为 'crazy' 生成 flash card。
产物[html]: outputs\skill_runs\crazy.html
stdout:
已生成: outputs\skill_runs\crazy.html

# 验证真实产物生成
(base) PS E:\ai\week13harness和skills\week13 skills和harness> Test-Path outputs\skill_runs\crazy.html
True

# 验证 references 是按需加载
(base) PS E:\ai\week13harness和skills\week13 skills和harness> python -m skill_harness.cli inspect baoyu-diagram --request "画一个系统架构图"
<frozen runpy>:128: RuntimeWarning: 'skill_harness.cli' found in sys.modules after import of package 'skill_harness', but prior to execution of 'skill_harness.cli'; this may result in unpredictable behaviour
[stage 0] 已根据元数据选中 skill
stage 1: 已加载 SKILL.md (7818 chars, 约 1954 tokens)
stage 2: 已加载引用 references\architecture.md (1741 chars, 约 435 tokens)，原因：请求内容匹配到 architecture.md
上下文总量估算：约 2389 tokens

# 验证流程图
(base) PS E:\ai\week13harness和skills\week13 skills和harness> python -m skill_harness.cli inspect baoyu-diagram --request "画一个流程图"
<frozen runpy>:128: RuntimeWarning: 'skill_harness.cli' found in sys.modules after import of package 'skill_harness', but prior to execution of 'skill_harness.cli'; this may result in unpredictable behaviour
[stage 0] 已根据元数据选中 skill
stage 1: 已加载 SKILL.md (7818 chars, 约 1954 tokens)
stage 2: 已加载引用 references\flowchart.md (1261 chars, 约 315 tokens)，原因：请求内容匹配到 flowchart.md
上下文总量估算：约 2269 tokens

# 强制加载所有 references 的对照组
(base) PS E:\ai\week13harness和skills\week13 skills和harness> python -m skill_harness.cli inspect baoyu-diagram --request "画图" --load-all-refs
<frozen runpy>:128: RuntimeWarning: 'skill_harness.cli' found in sys.modules after import of package 'skill_harness', but prior to execution of 'skill_harness.cli'; this may result in unpredictable behaviour
[stage 0] 已根据元数据选中 skill
stage 1: 已加载 SKILL.md (7818 chars, 约 1954 tokens)
stage 2: 已加载引用 references\architecture.md (1741 chars, 约 435 tokens)，原因：用户显式传入 --load-all-refs
stage 2: 已加载引用 references\flowchart.md (1261 chars, 约 315 tokens)，原因：用户显式传入 --load-all-refs
stage 2: 已加载引用 references\sequence.md (2839 chars, 约 709 tokens)，原因：用户显式传入 --load-all-refs
stage 2: 已加载引用 references\structural.md (2644 chars, 约 661 tokens)，原因：用户显式传入 --load-all-refs
上下文总量估算：约 4074 tokens

# 测试
(base) PS E:\ai\week13harness和skills\week13 skills和harness> python -m unittest discover -s tests -p "test_*.py"
...
----------------------------------------------------------------------
Ran 3 tests in 0.003s

OK