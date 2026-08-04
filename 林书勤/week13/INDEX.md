# 项目索引与导航

## 📚 文档导航

### 🚀 新手入门
1. **README.md** - 项目概述 (80 行)
   - 核心设计理念
   - 四层对应关系
   - 快速开始

2. **QUICKSTART.md** - 三分钟快速上手 (150 行)
   - 最快入门指南
   - 常用命令速查
   - 参数示例

### 📖 深入学习
3. **ARCHITECTURE.md** - 完整技术架构 (400 行)
   - 四阶段流水线详解
   - 五个核心模块设计
   - 算法与设计模式

4. **USAGE_GUIDE.md** - 详尽使用手册 (800 行)
   - CLI 完整教程
   - Python API 指南
   - 自定义 Skill 开发
   - 问题排查与最佳实践

### 📋 参考与总结
5. **SUMMARY.md** - 项目总结与成就 (150 行)
   - 任务完成情况
   - 关键特性汇总
   - 教学价值与亮点

6. **CHECKLIST.md** - 完成清单 (200 行)
   - 所有项目验证
   - 功能完整性检查
   - 代码质量评估

7. **INDEX.md** - 本文档
   - 导航与索引
   - 文件快速查找

---

## 🗂️ 代码结构

### 核心模块 (src/)

| 文件 | 行数 | 职责 | Week13 对应 |
|------|------|------|-----------|
| skill_loader.py | 230 | Skill 发现与加载 | Layer 3 (Markdown) |
| skill_context.py | 250 | 上下文构建与注入 | Layer 1 (工作记忆) |
| skill_executor.py | 310 | 渐进式执行引擎 | Memory Flush 三步 |
| skill_state.py | 330 | 状态管理与持久化 | Layer 2 (SQLite) |
| skill_harness.py | 450 | 主程序与 CLI | 外层 API |

**总计**: 1570 行核心代码

### 示例 Skills (skills/)

| 目录 | 依赖 | 演示 |
|------|------|------|
| demo-greeting/ | 无 | 基础参数处理、多语言多风格 |
| demo-data-process/ | 无 | 复杂逻辑、多操作模式 |
| demo-report-gen/ | demo-data-process | 自动依赖注入、链式执行 |

**总计**: 3 个完整示例

### 入口点 & 工具

| 文件 | 用途 |
|------|------|
| skill_harness.py | CLI 入口 |
| test_harness.py | 综合测试脚本 |

---

## 🎯 功能快速定位

### 我想要...

#### 🆕 快速开始
→ **QUICKSTART.md** 或 **README.md**

#### 🔧 使用 CLI
→ **USAGE_GUIDE.md** → "CLI 接口使用" 部分  
快速命令：`python skill_harness.py --help`

#### 📝 开发自定义 Skill
→ **USAGE_GUIDE.md** → "创建自定义 Skill" 部分  
示例参考：`skills/demo-greeting/`

#### 🔗 理解依赖管理
→ **ARCHITECTURE.md** → "依赖管理" 部分  
示例参考：`skills/demo-report-gen/`

#### 🐍 使用 Python API
→ **USAGE_GUIDE.md** → "Python API 使用" 部分  
测试参考：`test_harness.py`

#### 🔍 了解内部设计
→ **ARCHITECTURE.md** → "四阶段执行流水线" 部分

#### 📊 查看项目统计
→ **SUMMARY.md** → "项目统计" 部分  
或 **CHECKLIST.md** → "项目统计" 部分

#### 🧪 运行测试
```bash
python test_harness.py
```
→ 参考：`test_harness.py`

#### ⚙️ 优化性能
→ **USAGE_GUIDE.md** → "性能优化" 部分

#### 🐛 调试问题
→ **USAGE_GUIDE.md** → "调试技巧" 部分  
或 **USAGE_GUIDE.md** → "常见问题" 部分

---

## 📊 项目规模

```
总代码量:        2700+ 行
├─ 核心代码:     1570 行
├─ 示例代码:     200+ 行
├─ 测试代码:     350+ 行
└─ 文档:         1200+ 行

文件统计:
├─ 核心模块:     5 个
├─ 示例 skills:  3 个
├─ 文档:         7 个
└─ 工具脚本:     2 个
总计:           17 个文件
```

---

## 🎓 学习路径

### 路径 1: 快速上手 (30 分钟)
1. 阅读 **README.md** (5 分钟)
2. 阅读 **QUICKSTART.md** (5 分钟)
3. 运行 `test_harness.py` (10 分钟)
4. 尝试几个 CLI 命令 (10 分钟)

### 路径 2: 深入理解 (2 小时)
1. 阅读 **README.md** (10 分钟)
2. 阅读 **ARCHITECTURE.md** (30 分钟)
3. 阅读 **USAGE_GUIDE.md** (40 分钟)
4. 研究代码 (40 分钟)

### 路径 3: 完全掌握 (半天)
1. 跟随上述路径 2
2. 创建自己的 skill (30 分钟)
3. 创建有依赖的 skill (30 分钟)
4. 集成到自己的项目 (1 小时)

---

## 🌟 核心概念

### 四层递进架构
```
Stage 1: Discovery   (Markdown 配置驱动)
  ↓
Stage 2: Context     (参数验证 + 自动注入)
  ↓
Stage 3: Execution   (事件流 + 异常恢复)
  ↓
Stage 4: Persistence (多层缓存 + 历史记录)
```

### 关键特性
- ✅ **动态发现**：自动扫描 skills/，无需注册代码
- ✅ **自动注入**：前置结果自动传递给后续 skills
- ✅ **事件流**：实时监控执行进度
- ✅ **三层缓存**：内存、数据库、参数级
- ✅ **异常恢复**：部分失败不影响整体

---

## 🔗 快速链接

| 需求 | 文件 | 位置 |
|------|------|------|
| 我需要运行代码 | test_harness.py | 根目录 |
| 我需要 CLI 帮助 | USAGE_GUIDE.md | "CLI 接口使用" |
| 我需要创建 skill | USAGE_GUIDE.md | "创建自定义 Skill" |
| 我需要 Python 代码 | test_harness.py | 根目录 |
| 我需要查看示例 | skills/ | 根目录/skills |
| 我需要理解架构 | ARCHITECTURE.md | 文档 |
| 我遇到了问题 | USAGE_GUIDE.md | "常见问题" |

---

## ✨ 推荐阅读顺序

### 对于项目管理者/评审者
1. **README.md** - 快速了解项目
2. **SUMMARY.md** - 查看完成情况
3. **CHECKLIST.md** - 验证完整性

### 对于使用者
1. **README.md** - 了解基本概念
2. **QUICKSTART.md** - 快速上手
3. **USAGE_GUIDE.md** - 查找具体操作

### 对于开发者
1. **README.md** - 项目概述
2. **ARCHITECTURE.md** - 深入设计
3. **src/*.py** - 研究实现
4. **skills/demo-* - 参考示例

### 对于学生
1. **README.md** - 背景知识
2. **ARCHITECTURE.md** - 学习设计
3. **USAGE_GUIDE.md** - 实践应用
4. **test_harness.py** - 验证学习成果

---

## 🚀 常用命令速查

```bash
# 查看所有 skills
python skill_harness.py discover

# 执行一个 skill
python skill_harness.py run demo-greeting -p '{"name":"Alice"}'

# 链式执行
python skill_harness.py chain demo-data-process,demo-report-gen -p '{"data":[1,2,3]}'

# 查看执行历史
python skill_harness.py history

# 查看统计信息
python skill_harness.py stats

# 运行测试
python test_harness.py
```

---

## 📞 获取帮助

| 问题类型 | 查找位置 |
|---------|---------|
| 如何开始? | README.md 或 QUICKSTART.md |
| 如何使用 CLI? | USAGE_GUIDE.md → CLI 部分 |
| 如何写 skill? | USAGE_GUIDE.md → 创建 Skill 部分 |
| 出错了怎么办? | USAGE_GUIDE.md → 常见问题部分 |
| 如何优化? | USAGE_GUIDE.md → 性能优化部分 |
| 系统工作原理? | ARCHITECTURE.md |
| 完成了什么? | SUMMARY.md 或 CHECKLIST.md |

---

## 🎁 额外资源

| 资源 | 位置 |
|------|------|
| 综合测试脚本 | test_harness.py |
| 示例 Skills | skills/demo-*/skill.py |
| 元数据示例 | skills/demo-*/SKILL.md |
| 项目依赖 | requirements.txt |

---

## 📈 项目进度

| 阶段 | 状态 | 文档 |
|------|------|------|
| 需求分析 | ✅ | README.md |
| 设计架构 | ✅ | ARCHITECTURE.md |
| 核心实现 | ✅ | src/ |
| 示例开发 | ✅ | skills/ |
| 功能测试 | ✅ | test_harness.py |
| 文档编写 | ✅ | *.md |
| 验收检查 | ✅ | CHECKLIST.md |

---

## 📝 许可和归属

**项目类型**：学术作业  
**课程**：Week 13 - Agent 记忆系统与 Skills  
**完成时间**：2024-01-01  
**代码量**：1570+ 行  
**文档量**：1200+ 行  

---

**🎉 欢迎使用 Skill Harness！**

选择一个上面的文档开始阅读，或直接运行 `python test_harness.py` 查看演示！
