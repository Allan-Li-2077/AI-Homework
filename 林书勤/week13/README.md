# 渐进式Skills加载执行Harness

基于 week13 学习的四层记忆模型、Memory Flush机制、Markdown配置理念，构建一套**动态发现、渐进式加载、链式执行**的skills系统。

## 核心设计

### 四阶段流水线

```
┌─────────────────────────────────────────────────────────┐
│  Stage 1: Skill Discovery (skill_loader.py)             │
│  - 扫描 skills/ 目录                                    │
│  - 读取 SKILL.md 元数据                                 │
│  - 构建 Skill Registry                                  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Stage 2: Context Building (skill_context.py)           │
│  - 依赖解析与拓扑排序                                    │
│  - 前置skill结果注入                                    │
│  - 参数验证与类型检查                                    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Stage 3: Progressive Execution (skill_executor.py)     │
│  - 按依赖顺序加载执行                                    │
│  - 流式输出中间结果                                      │
│  - 异常恢复与部分执行                                    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Stage 4: State Persistence (skill_state.py)            │
│  - SQLite 执行历史                                      │
│  - YAML 状态快照                                        │
│  - 结果缓存与复用                                        │
└─────────────────────────────────────────────────────────┘
```

## 目录结构

```
myweek13/
├── skills/                          # Skill 库（用户定义）
│   ├── demo-greeting/               # 示例 skill
│   │   ├── SKILL.md                 # 元数据
│   │   ├── skill.py                 # 实现
│   │   └── data/
│   ├── demo-data-process/
│   │   ├── SKILL.md
│   │   ├── skill.py
│   │   └── data/
│   └── ...
│
├── src/                             # Harness 核心
│   ├── skill_loader.py              # Stage 1: 发现与加载
│   ├── skill_context.py             # Stage 2: 上下文构建
│   ├── skill_executor.py            # Stage 3: 渐进式执行
│   ├── skill_state.py               # Stage 4: 状态管理
│   ├── skill_harness.py             # 主程序 + API
│   └── __init__.py
│
├── state/                           # 持久化数据
│   ├── skills.db                    # SQLite 历史
│   ├── cache/                       # 结果缓存
│   └── snapshots/                   # 执行快照
│
├── skill_harness.py                 # CLI 入口
├── requirements.txt
├── ARCHITECTURE.md                  # 技术文档
└── USAGE_GUIDE.md                   # 使用手册
```

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. CLI 示例
python skill_harness.py --help
python skill_harness.py discover              # 发现所有 skills
python skill_harness.py run demo-greeting     # 执行单个 skill
python skill_harness.py chain demo-greeting,demo-data-process  # 链式执行

# 3. Python API
from src.skill_harness import SkillHarness
harness = SkillHarness()
result = harness.run_skill("demo-greeting", name="Alice")
```

## 核心概念

### Skill 文件格式

每个 skill 目录必须包含 `SKILL.md`：

```yaml
---
name: demo-greeting
version: 1.0
description: 生成个性化问候
trigger: 用户要求生成问候时触发
dependencies: []  # 依赖的其他 skills
parameters:
  - name: name
    type: str
    required: true
  - name: tone
    type: str
    default: friendly
returns:
  type: str
  description: 生成的问候文本
---
```

### Skill 实现模板

```python
# skill.py
from typing import Any, Dict

class SkillImpl:
    def __init__(self, context: Dict[str, Any]):
        self.context = context
    
    async def execute(self, **kwargs) -> Any:
        """主要执行逻辑"""
        name = kwargs.get('name', 'Friend')
        tone = kwargs.get('tone', 'friendly')
        # ... 实现逻辑
        return f"Hello, {name}!"
```

## 四层记忆对应关系

| Harness 组件 | Week13 概念 | 对应 |
|------------|-----------|------|
| Skill Registry | Layer 3 (Markdown配置) | SKILL.md 元数据 |
| Context Injection | Layer 1 (工作记忆) | 前置skill结果注入 |
| Execution Pipeline | Memory Flush 三步 | 依赖解析→渐进加载→状态持久化 |
| State DB | Layer 2 (SQLite) | 执行历史 + 结果缓存 |

## 教学价值

- **动态发现**: 学习文件系统扫描、元数据解析
- **依赖管理**: 理解图论（拓扑排序）在工作流中的应用
- **渐进式执行**: 体验流式加载、部分失败恢复
- **状态持久化**: 掌握 SQLite、YAML 的数据组织
- **LLM集成**: 可扩展的 prompt 注入机制

---

更多详情见 `ARCHITECTURE.md` 和 `USAGE_GUIDE.md`
