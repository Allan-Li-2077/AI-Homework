# 渐进式 Skills 加载执行 Harness - 技术架构

## 核心设计哲学

本 Harness 基于 week13 四层记忆系统的设计理念，构建一套**动态发现、渐进式执行、链式依赖管理**的 skills 框架。

### 对应关系

| Week13 概念 | Harness 组件 | 职责 |
|-----------|------------|------|
| Layer 3（Markdown 配置） | SkillLoader | SKILL.md 元数据发现与解析 |
| Layer 1（工作记忆） | SkillContext | 当前执行的上下文注入 |
| Memory Flush 三步 | SkillExecutor | 依赖分析 → 渐进执行 → 结果收集 |
| Layer 2（SQLite 历史） | SkillState | 执行记录持久化 |

---

## 四阶段执行流水线

```
┌──────────────────────────────────────────────────────────────┐
│ Stage 1: Discovery (skill_loader.py)                         │
│ ✓ 扫描 skills/ 目录                                          │
│ ✓ 读取 SKILL.md frontmatter                                  │
│ ✓ 构建全局 SkillRegistry                                     │
│ ✓ 验证依赖声明                                                │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Stage 2: Context Building (skill_context.py)                 │
│ ✓ 解析 skill 之间的依赖关系                                   │
│ ✓ 拓扑排序确定执行顺序                                        │
│ ✓ 收集前置 skill 的执行结果                                   │
│ ✓ 构建执行上下文（Context Window）                           │
│ ✓ 参数验证与类型检查                                          │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Stage 3: Progressive Execution (skill_executor.py)           │
│ ✓ 加载 Python 实现模块                                       │
│ ✓ 按依赖顺序执行 skills                                      │
│ ✓ 流式事件推送（ExecutionEvent）                             │
│ ✓ 异常捕获与恢复                                              │
│ ✓ 中间结果注入下一阶段                                        │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Stage 4: State Persistence (skill_state.py)                  │
│ ✓ SQLite 执行历史记录                                        │
│ ✓ 内存缓存（工作记忆）                                        │
│ ✓ YAML 快照检查点                                            │
│ ✓ 统计信息与查询                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 模块详解

### 1. SkillLoader（Stage 1）

**职责**：发现和加载所有 skills

**核心类**：

- `SkillMetadata`: 单个 skill 的元数据容器
  ```python
  @dataclass
  class SkillMetadata:
      name: str              # "demo-greeting"
      version: str           # "1.0"
      description: str
      trigger: str           # 触发条件描述
      dependencies: List[str]  # ["skill-a", "skill-b"]
      parameters: List[SkillParameter]
      returns: Dict[str, str]
  ```

- `SkillRegistry`: 全局注册表
  ```python
  registry = SkillRegistry()
  registry.register(metadata)          # 注册
  registry.get("skill-name")           # 查询
  registry.topological_sort([names])   # 依赖排序
  ```

- `SkillLoader`: 文件扫描 + 解析
  ```python
  loader = SkillLoader(skills_dir)
  registry = loader.discover_and_load()
  ```

**设计亮点**：

- 基于 Markdown frontmatter 的自文档化配置
- 简易 YAML 解析器（不依赖第三方库）
- 依赖验证（发现循环依赖）

---

### 2. SkillContext（Stage 2）

**职责**：构建执行上下文，管理参数和依赖注入

**核心类**：

- `SkillContext`: 单次执行的完整上下文
  ```python
  context = SkillContext(
      metadata=skill_metadata,
      user_params={"name": "Alice"},
      dependency_results={"demo-greeting": "Hello Alice!"},
      config={...}
  )
  ```

- `ContextBuilder`: 上下文工厂与依赖管理
  ```python
  builder = ContextBuilder(registry)
  
  # 单个 skill
  context, errors = builder.build_context(
      "skill-name",
      {"param1": "value1"},
      dependency_results={}
  )
  
  # 链式执行
  contexts, errors = builder.build_chain_contexts(
      ["skill-a", "skill-b"],
      user_params={}
  )
  ```

**设计亮点**：

- 自动依赖注入（skill-name → skill_name 参数）
- 参数类型验证与默认值处理
- 生成 LLM prompt 前缀（for 集成 LLM 的 skills）

---

### 3. SkillExecutor（Stage 3）

**职责**：协调 skills 的渐进式执行，管理事件流

**核心类**：

- `ExecutionEvent`: 执行事件（观察者模式）
  ```python
  event = ExecutionEvent(
      timestamp="2024-01-01T12:00:00",
      stage="execution",         # discovery/context/execution/completion
      skill_name="demo-greeting",
      status=ExecutionStatus.SUCCESS,
      message="执行成功",
      result={"greeting": "..."},
      error=None
  )
  ```

- `SkillExecutor`: 主执行引擎
  ```python
  executor = SkillExecutor(skills_dir, on_event=callback)
  
  # 初始化（发现 skills）
  await executor.initialize()
  
  # 单个执行
  async for event in executor.run_skill("demo-greeting", {"name": "Alice"}):
      print(event.message)
  
  # 链式执行
  async for event in executor.run_skill_chain(
      ["demo-data-process", "demo-report-gen"],
      {"data": [1, 2, 3]}
  ):
      print(event.message)
  ```

**执行流程**（类比 Memory Flush 三步）：

```
Pass 1: Discovery（依赖分析）
  - 对要执行的 skills 列表进行拓扑排序
  - 检测循环依赖
  - 确定执行顺序

Pass 2: Context Building（上下文构建）
  - 为每个 skill 构建执行上下文
  - 收集前置 skill 的结果
  - 验证参数完整性

Pass 3: Progressive Execution（逐个执行）
  - 加载 skill 实现
  - 执行 skill.execute()
  - 发送执行事件
  - 注入结果供下一步使用
  - 异常捕获与处理
```

**设计亮点**：

- 异步/等待机制（async/await）
- 事件流（观察者模式）
- 中间结果自动注入
- 异常恢复（单个 skill 失败不影响后续）

---

### 4. SkillState（Stage 4）

**职责**：状态持久化与结果缓存

**核心类**：

- `ExecutionRecord`: 执行记录
  ```python
  record = ExecutionRecord(
      skill_name="demo-greeting",
      status="success",
      params={"name": "Alice"},
      result={"greeting": "..."},
      duration_ms=150
  )
  ```

- `SkillState`: 状态管理器
  ```python
  state = SkillState(state_dir)
  
  # SQLite 持久化
  record_id = state.save_record(record)
  records = state.get_latest_records("demo-greeting", limit=10)
  cached = state.get_success_result("demo-greeting")  # 缓存复用
  
  # 内存缓存（工作记忆）
  state.cache_result("key", value)
  state.get_cached_result("key")
  
  # YAML 快照
  state.save_snapshot("checkpoint-1", {"results": {...}})
  state.load_snapshot("checkpoint-1")
  
  # 统计
  stats = state.get_statistics()
  
  # 清理（Compaction）
  state.clear_old_records(keep_count=50)
  ```

**数据持久化**：

- **SQLite** (`state/skills.db`)：长期记录
  ```sql
  CREATE TABLE execution_history (
      id INTEGER PRIMARY KEY,
      timestamp TEXT,
      skill_name TEXT,
      status TEXT,           -- "success", "failed", "skipped"
      params TEXT,           -- JSON
      result TEXT,           -- JSON
      error TEXT,
      duration_ms INTEGER
  );
  ```

- **内存缓存**：工作记忆（提高复用效率）
- **YAML 快照** (`state/snapshots/`）：检查点

---

## Skill 接口规范

### SKILL.md 格式

```yaml
---
name: skill-name              # 唯一标识
version: 1.0
description: 描述
trigger: 触发条件描述
dependencies: [dep1, dep2]    # 依赖列表
parameters:
  - name: param_name
    type: str|int|float|bool|list|dict|any
    required: true|false
    default: value
    description: 参数描述
returns:
  type: 返回类型
  description: 返回描述
---
# Markdown 格式的详细说明
```

### skill.py 实现

```python
class SkillImpl:
    def __init__(self, context: SkillContext):
        self.context = context
    
    async def execute(self, **kwargs) -> Any:
        """
        主执行逻辑
        
        Args:
            **kwargs: 合并后的参数（用户参数 + 自动注入的依赖结果）
        
        Returns:
            任意返回值（建议使用 dict 便于后续链式调用）
        """
        # 实现逻辑
        return result
```

---

## 示例 Skills

### 1. demo-greeting（无依赖）

生成个性化问候。

**使用**：
```python
harness.run_skill("demo-greeting", {"name": "Alice", "tone": "friendly"})
```

### 2. demo-data-process（无依赖）

处理数据列表。

**使用**：
```python
harness.run_skill("demo-data-process", {"data": [1,2,3,4,5], "operation": "summary"})
```

**返回**：
```json
{
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
```

### 3. demo-report-gen（依赖 demo-data-process）

生成综合报告。

**演示依赖注入**：

```python
# 链式执行（自动管理依赖）
result = harness.run_skill_chain(
    ["demo-data-process", "demo-report-gen"],
    {"data": [1,2,3,4,5]}
)
```

**执行顺序**（自动）：
1. demo-data-process 执行，得到 {success: true, ...}
2. 结果自动注入到 demo-report-gen 的 demo_data_process 参数
3. demo-report-gen 执行，生成报告

---

## 异步执行模型

Harness 内部采用异步执行（async/await），对外提供同步 API（包装器）。

### 内部异步（核心层）

```python
# SkillExecutor 使用 async/await
async for event in executor.run_skill_chain([...], params):
    print(event.message)
```

### 对外同步（API 层）

```python
# SkillHarness 提供同步 API
result = harness.run_skill_chain([...], params)
```

**实现原理**：

```python
loop = asyncio.new_event_loop()
try:
    result = loop.run_until_complete(async_function())
finally:
    loop.close()
```

---

## 事件流（观察者模式）

Harness 在执行过程中推送事件，支持实时监听。

### 事件类型

| Stage | Status | 含义 |
|-------|--------|------|
| discovery | PENDING | 正在发现 |
| discovery | SUCCESS | 发现完成 |
| context | PENDING | 正在构建上下文 |
| context | SUCCESS | 上下文就绪 |
| context | RUNNING | 上下文警告 |
| execution | PENDING | 加载中 |
| execution | RUNNING | 执行中 |
| execution | SUCCESS | 执行成功 |
| execution | FAILED | 执行失败 |
| execution | SKIPPED | 跳过（缺失依赖） |
| completion | SUCCESS | 链执行完成 |

### 监听事件

```python
def on_event(event: ExecutionEvent):
    print(f"[{event.skill_name}] {event.message}")

harness = SkillHarness(on_event=on_event)
result = harness.run_skill("demo-greeting", {"name": "Alice"})

# 输出：
# [__system__] 发现 3 个 skills
# [demo-greeting] 正在构建执行上下文...
# [demo-greeting] 执行上下文已就绪
# [demo-greeting] 正在加载 skill 实现...
# [demo-greeting] 开始执行...
# [demo-greeting] 执行成功
```

---

## 缓存与复用

Harness 支持三层缓存：

1. **内存缓存**（工作记忆）
   - 同一会话内快速复用
   - `state.cache_result(key, value)`

2. **数据库缓存**（长期记忆）
   - 最近一次成功执行的结果
   - `state.get_success_result(skill_name)`

3. **参数级缓存**
   - CLI `-c` 或 `--no-cache` 控制

---

## 依赖管理

### 拓扑排序

Harness 使用 **Kahn 算法**进行拓扑排序，确定执行顺序。

```python
# 输入：["skill-c", "skill-a"]
# 其中 skill-c 依赖 skill-a 和 skill-b
# 其中 skill-a 无依赖

# 执行顺序：skill-a → skill-b → skill-c
sorted_names = registry.topological_sort(["skill-c", "skill-a"])
```

### 循环依赖检测

如果 skills 形成循环依赖，harness 会拒绝执行并报错。

```python
# 检测
errors = registry.validate_dependencies()
if errors:
    for error in errors:
        print(error)
```

---

## 错误恢复

Harness 支持**部分失败恢复**：

- 某个 skill 执行失败 ❌ → 后续依赖的 skills 标记为 SKIPPED ∅
- 不中止整个链的执行
- 返回部分结果（已成功的 skills）

```python
result = harness.run_skill_chain(
    ["skill-a", "skill-b", "skill-c"],
    params
)

# 即使 skill-b 失败，skill-a 的结果仍然保留
print(result["results"])  # {"skill-a": result_a, "skill-c": result_c}
```

---

## 与 Week13 的对应关系

| Week13 特性 | Harness 实现 | 代码位置 |
|-----------|------------|---------|
| 四层记忆加载 | Stage 1-4 的顺序加载 | `skill_executor.py` |
| Markdown 配置 | SKILL.md frontmatter | `skill_loader.py` |
| System Prompt 拼接 | Context 注入 | `skill_context.py` |
| Memory Flush 三步 | 三阶段执行 | `skill_executor.py` |
| SQLite 持久化 | execution_history 表 | `skill_state.py` |
| 混合检索（Layer 4） | 结果缓存与复用 | `skill_state.py` |
| HEARTBEAT 调度 | 可扩展的任务注册机制 | `skill_executor.py` |
| 向量化 | 结果序列化 | `skill_state.py` |

---

## 性能特性

- **启动时间**：O(n)（n = skill 数量）
  - 文件扫描 + 元数据解析
  
- **执行时间**：O(sum(skill_times))
  - 大部分时间由各 skill 的执行时间决定
  - 可以 async/await 并行执行（未来扩展）

- **内存占用**：O(m)（m = 结果总大小）
  - 内存缓存 + SQLite 索引

---

## 扩展点

1. **新增 Skill**：在 `skills/` 目录添加新的 `skill-name/` 子目录
2. **自定义 Context**：继承 `SkillContext` 添加业务特定字段
3. **并行执行**：修改 `SkillExecutor` 使用 `asyncio.gather()`
4. **Web API**：使用 FastAPI 包装 `SkillHarness`
5. **LLM 集成**：修改 skill 实现，调用 LLM API

---

## 总结

这套 Harness 系统通过**四层递进、三步执行、链式依赖、事件驱动**的设计，实现了：

✅ 动态发现与加载 skills  
✅ 灵活的参数验证与依赖注入  
✅ 渐进式的执行与中间结果收集  
✅ 完整的状态持久化与缓存  
✅ 透明的错误恢复与部分执行  

充分体现了 week13 四层记忆系统的设计理念，并将其推广到通用的 skills 执行框架。
