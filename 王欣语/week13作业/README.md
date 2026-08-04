# Skill Harness - 渐进式 Skill 加载执行框架

基于 Week 13 "Harness 和 Skills" 课程学习成果实现的轻量级 Skill 编排框架。

## 核心概念

### 什么是 Harness？

Harness（ harness 原意为"马具/ harness"）在 AI Agent 语境中是一个**技能编排框架**，负责：

1. **发现（Discovery）**：扫描目录找到所有 Skill
2. **加载（Loading）**：渐进式解析 Skill 的元数据和执行逻辑
3. **执行（Execution）**：根据用户输入匹配并调用对应的 Skill
4. **生命周期管理**：初始化 → 匹配 → 执行 → 清理

### 什么是 Skill？

Skill 是一个可独立执行的功能单元，由以下部分组成：

- `SKILL.md`：元数据文件（YAML frontmatter + Markdown 说明）
- `script.py`：执行脚本（Python/TypeScript/Shell）

## 项目结构

```
week13作业/
├── config.py              # 配置管理
├── skill_loader.py        # Skill 元数据解析 + 渐进式加载
├── skill_matcher.py       # 意图匹配引擎
├── skill_executor.py      # 脚本执行引擎
├── harness.py             # 核心编排框架
├── cli.py                 # 命令行交互界面
├── skills/                # 示例 Skill 目录
│   ├── hello-world/       # 问候 Skill
│   │   ├── SKILL.md
│   │   └── script.py
│   └── word-counter/      # 字数统计 Skill
│       ├── SKILL.md
│       └── script.py
└── README.md
```

## 渐进式加载设计

本框架的核心设计是**渐进式加载**：

| 阶段 | 加载内容 | 内存占用 | 速度 |
|------|---------|---------|------|
| 启动时 | 只解析 SKILL.md 的 YAML frontmatter（元数据） | 低 | 快 |
| 匹配时 | 操作元数据，不加载脚本 | 极低 | 极快 |
| 执行时 | 完整加载 Skill 内容 + 执行脚本 | 按需 | 正常 |

**优势**：
- 启动快速（不加载脚本内容）
- 内存高效（只加载用到的 Skill）
- 响应及时（元数据匹配速度快）

## 快速开始

### 1. 运行 CLI

```bash
cd /Users/wangxinyu/Desktop/python/最新/week13作业
python cli.py
```

### 2. 测试 Skill

```
🎯 > 你好
👋 下午好！我是 Hello World Skill。
🕐 当前时间: 2026-07-30 14:32:10
💬 你说了: 你好

✨ 这是 Harness 渐进式加载执行的第一个 Skill！
```

```
🎯 > 统计字数 这是一段测试文本
📊 文本统计结果
  ─────────────────────────────
  总字符数:     10
  非空字符数:   8
  中文字符:     8
  单词数:       1
  总行数:       1
  非空行数:     1
  ─────────────────────────────
💡 文本内容: 这是一段测试文本
```

### 3. CLI 命令

| 命令 | 说明 |
|------|------|
| `<任意输入>` | 触发 Skill 匹配与执行 |
| `/list` | 列出所有已加载的 Skill |
| `/info <name>` | 查看指定 Skill 的详细信息 |
| `/reload` | 重新扫描并加载所有 Skill |
| `/help` | 显示帮助信息 |
| `/quit` | 退出程序 |

## 创建自己的 Skill

### 1. 创建目录结构

```bash
mkdir skills/my-skill
touch skills/my-skill/SKILL.md
touch skills/my-skill/script.py
```

### 2. 编写 SKILL.md

```markdown
---
name: my-skill
description: 我的自定义 Skill
version: 1.0.0
triggers:
  - 触发词1
  - 触发词2
script_type: python
---

# My Skill

功能说明...

script: script.py
```

### 3. 编写 script.py

```python
#!/usr/bin/env python3
import sys

def main():
    user_input = sys.argv[1] if len(sys.argv) > 1 else ""
    print(f"处理输入: {user_input}")

if __name__ == "__main__":
    main()
```

### 4. 测试

```bash
python cli.py
🎯 > 触发词1
```

## 匹配策略

框架使用三层递进匹配策略：

1. **精确匹配**（分数=1.0）：用户输入直接包含 trigger 关键词
2. **模糊匹配**（分数=0~0.95）：基于字符重叠度和词覆盖度计算相似度
3. **描述匹配**（分数=0~0.5）：与 Skill description 做关键词匹配

匹配阈值默认为 0.3，可通过 `--threshold` 参数调整。

## 技术栈

| 组件 | 说明 |
|------|------|
| Python 3.8+ | 核心语言 |
| dataclasses | 数据模型 |
| subprocess | 脚本执行 |
| logging | 日志记录 |

## 从教学文件搬运的设计思路

| 来源 | 搬运内容 |
|------|---------|
| `skills/baoyu-diagram/SKILL.md` | Skill 元数据格式（YAML frontmatter）、脚本调用方式 |
| `skills/flash-card/SKILL.md` | Skill 触发条件定义、数据文件路径规范 |
| `agent_memory_system/src/` | 模块化的架构设计（loader/retrieval/execution 分离）、配置管理 |
| `agent_memory_system/USAGE_GUIDE.md` | CLI 命令设计思路、用户交互模式 |

## 扩展方向

1. **更智能的匹配**：接入 LLM 做语义匹配
2. **Skill 依赖管理**：支持 Skill 之间的依赖关系
3. **并行执行**：支持多个 Skill 同时执行
4. **结果缓存**：缓存 Skill 执行结果
5. **Web UI**：像 `agent_memory_system` 一样提供可视化界面
