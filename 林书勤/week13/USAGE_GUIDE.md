# 使用指南 - Skill Harness

## 快速开始

### 1. 环境准备

```bash
# 进入项目目录
cd myweek13

# 安装依赖
pip install -r requirements.txt
```

### 2. 发现 Skills

```bash
# 列出所有 skills
python skill_harness.py discover
```

**输出示例**：

```
════════════════════════════════════════════════════════════════════════════════
                            发现的 Skills
════════════════════════════════════════════════════════════════════════════════

📦 demo-greeting (v1.0)
   为指定用户生成个性化问候文本
   参数:
      - name (str) [必需]
      - tone (str) [可选] = friendly
      - language (str) [可选] = zh

📦 demo-data-process (v1.0)
   处理数据列表并生成统计报告
   参数:
      - data (list) [必需]
      - operation (str) [可选] = summary

📦 demo-report-gen (v1.0)
   生成综合报告（依赖前置数据）
   依赖: demo-data-process
   参数:
      - title (str) [可选] = 数据分析报告
      - demo_data_process (dict) [可选]
```

### 3. 执行单个 Skill

#### 基础执行

```bash
# 最简形式（使用默认参数）
python skill_harness.py run demo-greeting -p '{"name":"Alice"}'
```

#### 带自定义参数

```bash
# 指定风格和语言
python skill_harness.py run demo-greeting -p '{"name":"小明","tone":"formal","language":"zh"}'
```

**输出示例**：

```
────────────────────────────────────────────────────────────────────────────────
                             执行结果
────────────────────────────────────────────────────────────────────────────────

✅ 状态: success
⏱️  耗时: 145ms

📤 结果:
   "尊敬的小明，祝您安好。"

📋 执行事件 (5 条):
   ✓ [disc] __system__: 发现 3 个 skills
   · [cont] demo-greeting: 正在构建执行上下文...
   ✓ [cont] demo-greeting: 执行上下文已就绪
   → [exec] demo-greeting: 开始执行...
   ✓ [exec] demo-greeting: 执行成功
```

#### 禁用缓存

```bash
# 加 --no-cache 强制重新执行
python skill_harness.py run demo-greeting -p '{"name":"Alice"}' --no-cache
```

---

### 4. 链式执行（演示依赖）

```bash
# 依次执行 demo-data-process 和 demo-report-gen
python skill_harness.py chain demo-data-process,demo-report-gen \
    -p '{"data":[1,2,3,4,5],"operation":"summary"}'
```

**执行流程**：

```
1️⃣  demo-data-process 执行
    输入: data=[1,2,3,4,5], operation="summary"
    输出: {
      "success": true,
      "operation": "summary",
      "count": 5,
      "sum": 15,
      "avg": 3.0,
      "min": 1,
      "max": 5,
      "median": 3,
      "stdev": 1.41
    }

2️⃣  demo-report-gen 自动接收前置结果
    前置结果自动注入为 demo_data_process 参数
    输出: 完整的报告对象，包含统计、分析、建议等
```

**输出示例**：

```
────────────────────────────────────────────────────────────────────────────────
                           链执行结果
────────────────────────────────────────────────────────────────────────────────

✅ 状态: success
⏱️  总耗时: 312ms

📤 执行结果 (2 个):
   • demo-data-process: {"success": true, "operation": "summary", ...}...
   • demo-report-gen: {"title": "数据分析报告", "sections": [...]}...

📋 执行事件 (15 条):
   ✓ [disc] __chain__: 发现 3 个 skills
   ... (省略中间事件)
   ✓ [comp] __chain__: 链执行完成，共 2 个成功
```

---

### 5. 查看执行历史

```bash
# 显示最近 10 条记录
python skill_harness.py history

# 过滤特定 skill
python skill_harness.py history -s demo-greeting

# 自定义数量
python skill_harness.py history -l 20
```

**输出示例**：

```
────────────────────────────────────────────────────────────────────────────────
                           执行历史
────────────────────────────────────────────────────────────────────────────────

✓ demo-greeting (2024-01-01T14:30:45.123456) 耗时 145ms
✓ demo-data-process (2024-01-01T14:30:22.654321) 耗时 89ms
✓ demo-report-gen (2024-01-01T14:30:25.987654) 耗时 78ms
```

### 6. 查看统计信息

```bash
python skill_harness.py stats
```

**输出示例**：

```
────────────────────────────────────────────────────────────────────────────────
                            执行统计
────────────────────────────────────────────────────────────────────────────────

总记录数: 42
缓存大小: 3
快照数: 2

按状态统计:
  success: 40
  failed: 2

按 Skill 统计:
  demo-greeting: 15
  demo-data-process: 12
  demo-report-gen: 15
```

---

## Python API 使用

### 基础使用

```python
from src.skill_harness import SkillHarness

# 初始化
harness = SkillHarness()
harness.initialize()

# 发现 skills
skills = harness.discover_skills()
for skill in skills:
    print(f"{skill['name']}: {skill['description']}")
```

### 执行单个 Skill

```python
# 执行
result = harness.run_skill(
    "demo-greeting",
    params={"name": "Alice", "tone": "friendly"}
)

# 检查结果
if result["status"] == "success":
    print(f"结果: {result['result']}")
    print(f"耗时: {result['duration_ms']}ms")
    
    # 查看执行事件
    for event in result['events']:
        print(f"  {event.stage}: {event.message}")
else:
    print(f"失败: {result.get('error')}")
```

### 链式执行

```python
# 链式执行（自动管理依赖）
result = harness.run_skill_chain(
    ["demo-data-process", "demo-report-gen"],
    params={"data": [1, 2, 3, 4, 5]}
)

# 查看各 skill 的结果
for skill_name, skill_result in result["results"].items():
    print(f"{skill_name}:")
    print(f"  {skill_result}")
```

### 缓存与复用

```python
# 第一次执行（真实执行）
result1 = harness.run_skill(
    "demo-greeting",
    params={"name": "Alice"}
)
print(result1["duration_ms"])  # 145ms

# 第二次执行（使用缓存，更快）
result2 = harness.run_skill(
    "demo-greeting",
    params={"name": "Alice"},
    use_cache=True  # 默认为 True
)
print(result2["duration_ms"])  # 1ms（缓存）
print(result2.get("from_cache"))  # True

# 强制重新执行
result3 = harness.run_skill(
    "demo-greeting",
    params={"name": "Alice"},
    use_cache=False
)
print(result3["duration_ms"])  # 145ms（重新执行）
```

### 执行历史与统计

```python
# 获取历史
records = harness.get_execution_history(
    skill_name="demo-greeting",
    limit=10
)

for record in records:
    print(f"{record['timestamp']}: {record['status']}")

# 获取统计
stats = harness.get_statistics()
print(f"总执行数: {stats['total_records']}")
print(f"缓存大小: {stats['cache_size']}")
print(f"Skill 执行统计: {stats['skill_counts']}")
```

### 事件监听

```python
def on_event(event):
    """事件回调"""
    print(f"[{event.skill_name}] {event.message}")
    if event.error:
        print(f"  ✗ 错误: {event.error}")

# 创建 harness 并传入回调
harness = SkillHarness(on_event=on_event)
harness.initialize()

# 执行时会实时输出事件
result = harness.run_skill("demo-greeting", {"name": "Alice"})

# 输出：
# [__system__] 正在发现 skills...
# [__system__] 发现 3 个 skills
# [demo-greeting] 正在构建执行上下文...
# [demo-greeting] 执行上下文已就绪
# [demo-greeting] 正在加载 skill 实现...
# [demo-greeting] 开始执行...
# [demo-greeting] 执行成功
```

---

## 创建自定义 Skill

### 第 1 步：创建目录结构

```bash
mkdir -p skills/my-skill
touch skills/my-skill/SKILL.md
touch skills/my-skill/skill.py
```

### 第 2 步：编写 SKILL.md

```yaml
---
name: my-skill
version: 1.0
description: 我的自定义 skill 描述
trigger: 触发条件描述
dependencies: []
parameters:
  - name: input_text
    type: str
    required: true
    description: 输入文本
  - name: mode
    type: str
    required: false
    default: default
    description: 模式选择
returns:
  type: str
  description: 处理结果
---

# 我的 Skill

## 功能说明

详细描述你的 skill 的功能...
```

### 第 3 步：实现 skill.py

```python
class SkillImpl:
    def __init__(self, context):
        self.context = context
    
    async def execute(self, **kwargs) -> str:
        """
        Args:
            input_text: 输入文本
            mode: 模式
        
        Returns:
            处理结果字符串
        """
        input_text = kwargs.get("input_text", "")
        mode = kwargs.get("mode", "default")
        
        # 实现你的逻辑
        result = f"处理结果: {input_text.upper()}"
        
        return result
```

### 第 4 步：测试

```bash
# 发现新 skill
python skill_harness.py discover

# 执行新 skill
python skill_harness.py run my-skill -p '{"input_text":"hello"}'
```

---

## 创建有依赖的 Skill

### 第 1 步：声明依赖

```yaml
---
name: my-processor
version: 1.0
description: 处理前置 skill 的结果
trigger: 当需要处理前置数据时
dependencies: [demo-data-process]  # 声明依赖
parameters:
  - name: demo_data_process
    type: dict
    required: false
    description: 前置结果（自动注入）
returns:
  type: dict
---
```

### 第 2 步：实现处理逻辑

```python
class SkillImpl:
    async def execute(self, **kwargs) -> dict:
        # 接收前置结果
        prev_result = kwargs.get("demo_data_process")
        
        if not prev_result:
            return {"error": "缺少前置数据"}
        
        # 基于前置结果进行处理
        result = {
            "prev_count": prev_result.get("count"),
            "processed": True,
            "new_data": prev_result.get("sum") * 2,
        }
        
        return result
```

### 第 3 步：链式执行

```bash
# 依赖会自动管理
python skill_harness.py chain demo-data-process,my-processor \
    -p '{"data":[1,2,3]}'

# 或在 Python 中
result = harness.run_skill_chain(
    ["demo-data-process", "my-processor"],
    params={"data": [1, 2, 3]}
)
```

---

## 调试技巧

### 1. 启用详细日志

```python
import logging

# 设置日志级别
logging.basicConfig(level=logging.DEBUG)

harness = SkillHarness()
harness.initialize()
result = harness.run_skill("demo-greeting", {"name": "Alice"})

# 输出详细的执行日志
```

### 2. 检查执行事件

```python
result = harness.run_skill("demo-greeting", {"name": "Alice"})

# 逐个检查事件
for event in result['events']:
    print(f"""
    Stage: {event.stage}
    Status: {event.status.value}
    Message: {event.message}
    Error: {event.error}
    Result: {event.result}
    """)
```

### 3. 查看缓存状态

```python
stats = harness.get_statistics()
print(f"缓存大小: {stats['cache_size']}")

# 清空缓存
harness.state.clear_cache()
```

### 4. 查看执行记录

```python
# 查看最近的 5 条记录
records = harness.get_execution_history(limit=5)

for record in records:
    print(f"""
    Skill: {record['skill_name']}
    Status: {record['status']}
    Duration: {record['duration_ms']}ms
    Params: {record['params']}
    Error: {record['error']}
    """)
```

---

## 常见问题

### Q1: 如何处理 skill 执行失败？

**A**: Harness 支持部分失败恢复。如果链中一个 skill 失败，后续依赖的 skills 会标记为 SKIPPED。

```python
result = harness.run_skill_chain([...], params)

# 检查各 skill 状态
for event in result['events']:
    if event.status.value == "failed":
        print(f"❌ {event.skill_name} 失败: {event.error}")
    elif event.status.value == "skipped":
        print(f"∅ {event.skill_name} 被跳过")
    else:
        print(f"✓ {event.skill_name} 成功")
```

### Q2: 如何传递复杂参数？

**A**: 使用 JSON 格式，harness 会自动解析类型。

```bash
# 列表参数
python skill_harness.py run demo-data-process \
    -p '{"data":[1,2,3,4,5],"operation":"summary"}'

# 字典参数（嵌套）
python skill_harness.py run my-skill \
    -p '{"config":{"key":"value","nested":{"x":1}}}'
```

### Q3: 如何重用前置 skill 的结果？

**A**: 使用缓存机制。

```python
# 第一次执行 skill-a
result_a = harness.run_skill("skill-a", params)

# skill-b 自动从缓存获取 skill-a 的结果
result_b = harness.run_skill_chain(
    ["skill-a", "skill-b"],
    params
)
# skill-a 会使用缓存，不会重新执行
```

### Q4: 如何保存执行快照？

**A**: 使用 state 的快照功能。

```python
result = harness.run_skill_chain([...], params)

# 保存快照
harness.state.save_snapshot(
    "execution-20240101",
    {"results": result['results']}
)

# 加载快照
snapshot = harness.state.load_snapshot("execution-20240101")
print(snapshot["results"])

# 列出所有快照
snapshots = harness.state.list_snapshots()
```

### Q5: 如何监控执行性能？

**A**: 查看统计信息和执行记录。

```python
# 获取统计
stats = harness.get_statistics()
print(f"总执行数: {stats['total_records']}")

# 查看平均耗时
records = harness.get_execution_history("demo-greeting", limit=10)
avg_duration = sum(r['duration_ms'] for r in records) / len(records)
print(f"平均耗时: {avg_duration:.0f}ms")
```

---

## 最佳实践

1. **充分利用缓存**：重复执行相同参数的 skill 时，缓存可以显著提升性能

2. **合理设计依赖**：避免过深的依赖链，3-4 层为最优

3. **详细的错误处理**：在 skill 实现中返回 `{success: false, error: "..."}` 的结构，便于后续判断

4. **Markdown 文档**：充分利用 SKILL.md 的描述，让 skill 易于理解和维护

5. **参数验证**：在 execute 中显式验证参数，提供有意义的错误消息

6. **避免全局状态**：每个 skill 实例独立，不要依赖全局变量

7. **定期清理**：使用 `harness.state.clear_old_records()` 清理过期的执行记录

---

## 更多示例

详见 `skills/` 目录中的三个示例 skills：
- `demo-greeting/`: 基础 skill，演示参数处理
- `demo-data-process/`: 数据处理，演示复杂逻辑
- `demo-report-gen/`: 依赖演示，展示链式执行

---

## 获取帮助

```bash
# CLI 帮助
python skill_harness.py --help

# 特定命令帮助
python skill_harness.py run --help
python skill_harness.py chain --help
```

---

**祝你使用愉快！🎉**
