# 快速参考卡

## 三分钟快速开始

### 1. 安装

```bash
cd myweek13
pip install -r requirements.txt
```

### 2. 发现 Skills

```bash
python skill_harness.py discover
```

### 3. 执行示例

#### 基础执行
```bash
python skill_harness.py run demo-greeting -p '{"name":"Alice"}'
```

#### 链式执行（演示依赖注入）
```bash
python skill_harness.py chain demo-data-process,demo-report-gen \
    -p '{"data":[1,2,3,4,5],"operation":"summary"}'
```

---

## Python API 速查

```python
from src.skill_harness import SkillHarness

# 初始化
harness = SkillHarness()
harness.initialize()

# 执行单个 skill
result = harness.run_skill("demo-greeting", {"name": "Alice"})

# 链式执行
result = harness.run_skill_chain(
    ["demo-data-process", "demo-report-gen"],
    {"data": [1,2,3]}
)

# 查看结果
print(result["result"])  # 执行结果
print(result["duration_ms"])  # 耗时

# 查看历史
records = harness.get_execution_history()
stats = harness.get_statistics()
```

---

## CLI 命令速查

| 命令 | 说明 | 示例 |
|------|------|------|
| discover | 列出所有 skills | `python skill_harness.py discover` |
| run | 执行单个 skill | `python skill_harness.py run demo-greeting -p '{"name":"Alice"}'` |
| chain | 链式执行 | `python skill_harness.py chain skill-a,skill-b -p '{"data":[...]}'` |
| history | 查看历史 | `python skill_harness.py history -s demo-greeting -l 10` |
| stats | 查看统计 | `python skill_harness.py stats` |

---

## Skill 开发速查

### 第 1 步：创建 SKILL.md

```yaml
---
name: my-skill
version: 1.0
description: 描述
trigger: 触发条件
dependencies: []
parameters:
  - name: input
    type: str
    required: true
returns:
  type: str
---
# 详细说明
```

### 第 2 步：创建 skill.py

```python
class SkillImpl:
    def __init__(self, context):
        self.context = context
    
    async def execute(self, **kwargs):
        input_text = kwargs.get("input", "")
        return f"处理: {input_text}"
```

### 第 3 步：测试

```bash
python skill_harness.py discover
python skill_harness.py run my-skill -p '{"input":"hello"}'
```

---

## 核心概念

### 四阶段流水线

```
Stage 1: Discovery     → 发现所有 skills（Markdown 元数据）
  ↓
Stage 2: Context       → 构建执行上下文（参数验证 + 依赖注入）
  ↓
Stage 3: Execution     → 渐进式执行（事件流 + 异常恢复）
  ↓
Stage 4: Persistence   → 状态持久化（SQLite + 缓存 + 快照）
```

### 自动依赖注入

```
Skill A 返回结果 → 自动注入到 Skill B 的参数
规则: skill-name → skill_name (自动转换)

示例：
  Skill "demo-data-process" 的结果
  → 自动注入为 Skill "demo-report-gen" 的 demo_data_process 参数
```

### 三层缓存

| 层级 | 位置 | 用途 | 速度 |
|------|------|------|------|
| L1 | 内存 | 工作记忆 | 最快 |
| L2 | SQLite | 长期记忆 | 中等 |
| L3 | 参数级 | 快速复用 | 快 |

---

## 常见操作

### 禁用缓存
```bash
python skill_harness.py run demo-greeting --no-cache -p '{"name":"Alice"}'
```

### 过滤执行历史
```bash
python skill_harness.py history -s demo-greeting -l 5
```

### 查看统计信息
```bash
python skill_harness.py stats
```

### 自定义参数
```bash
# 列表
python skill_harness.py run demo-data-process -p '{"data":[1,2,3,4,5]}'

# 字典
python skill_harness.py run my-skill -p '{"config":{"key":"value"}}'
```

---

## 目录结构

```
myweek13/
├── src/                    # 核心模块
├── skills/                 # Skill 库（可扩展）
│   ├── demo-greeting/
│   ├── demo-data-process/
│   └── demo-report-gen/
├── state/                  # 数据存储（自动创建）
│   ├── skills.db           # SQLite
│   ├── cache/              # 缓存
│   └── snapshots/          # 快照
└── skill_harness.py        # CLI 入口
```

---

## 文档导航

| 文档 | 用途 |
|------|------|
| README.md | 项目概述 |
| ARCHITECTURE.md | 技术细节 |
| USAGE_GUIDE.md | 完整教程 |
| SUMMARY.md | 项目总结 |
| CHECKLIST.md | 完成清单 |
| **QUICKSTART.md** | **本文档** |

---

## 示例 Skills

### demo-greeting
无依赖，生成个性化问候。
```bash
python skill_harness.py run demo-greeting \
    -p '{"name":"Alice","tone":"friendly","language":"en"}'
```

### demo-data-process
处理数据列表，三种操作模式。
```bash
python skill_harness.py run demo-data-process \
    -p '{"data":[1,2,3,4,5],"operation":"summary"}'
```

### demo-report-gen
依赖 demo-data-process，演示依赖注入。
```bash
python skill_harness.py chain demo-data-process,demo-report-gen \
    -p '{"data":[1,2,3,4,5]}'
```

---

## 事件类型

| 事件类型 | 含义 |
|---------|------|
| ✓ SUCCESS | 执行成功 |
| ✗ FAILED | 执行失败 |
| · PENDING | 等待中 |
| → RUNNING | 执行中 |
| ∅ SKIPPED | 被跳过 |

---

## 参数类型支持

| 类型 | 示例 | 说明 |
|------|------|------|
| str | `"hello"` | 字符串 |
| int | `123` | 整数 |
| float | `3.14` | 浮点数 |
| bool | `true` | 布尔值 |
| list | `[1,2,3]` | 列表 |
| dict | `{"key":"value"}` | 字典 |

---

## 调试技巧

### 查看详细日志
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 查看事件流
```python
result = harness.run_skill("skill-name", params)
for event in result['events']:
    print(f"[{event.stage}] {event.message}")
```

### 查看缓存
```python
stats = harness.get_statistics()
print(f"缓存大小: {stats['cache_size']}")
```

---

## 常见问题速答

**Q: 如何创建有依赖的 skill？**
```yaml
dependencies: [skill-a, skill-b]  # 在 SKILL.md 中声明
```

**Q: 如何获取前置结果？**
```python
# 自动注入，参数名 = skill-name (转换为 snake_case)
prev_result = kwargs.get("demo_data_process")
```

**Q: 如何禁用缓存？**
```bash
python skill_harness.py run skill-name --no-cache
```

**Q: 如何处理执行失败？**
- 使用链式执行时，失败的 skill 后续依赖会标记为 SKIPPED
- 检查事件流中的 error 信息

**Q: 如何扩展系统？**
- 添加新 skill：在 skills/ 下创建新目录
- 自定义 context：继承 SkillContext
- Web API：使用 FastAPI 包装 SkillHarness

---

## 性能优化

1. **使用缓存**：默认启用，避免重复计算
2. **清理旧记录**：使用 `state.clear_old_records()` 维护数据库
3. **合理设计依赖**：避免过深的依赖链
4. **异步执行**：skills 默认异步调度

---

## 相关文件

- 完整教程：`USAGE_GUIDE.md`
- 技术细节：`ARCHITECTURE.md`
- 项目总结：`SUMMARY.md`
- 完成清单：`CHECKLIST.md`
- 代码示例：`test_harness.py`

---

**需要帮助？查阅对应文档或运行 `python test_harness.py` 查看示例！**
