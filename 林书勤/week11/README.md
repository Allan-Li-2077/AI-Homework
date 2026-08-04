# Week 11 - Function Calling Agent Loop 实战

## 作业概述

本周作业实现了一个完整的 **Agent Loop**，将原本单一的天气查询工具拆分为两个独立工具，并通过循环机制让 LLM 能够自主决定调用顺序和次数，实现链式推理。

## 作业要求

将 `get_weather(city)` 拆分为两个独立工具：

1. **geocode(city)**: 城市名 → 经纬度
2. **get_weather_by_coords(lat, lon)**: 经纬度 → 天气数据

同时支持三种调用模式：

| 用户问题 | 工具调用链 | 模式 |
|----------|-----------|------|
| "宁德今天的天气怎么样？" | `geocode` → `get_weather_by_coords` | 链式调用 |
| "北京的经纬度是多少？" | `geocode` | 单工具独立 |
| "经度116.4、纬度39.9的天气如何？" | `get_weather_by_coords` | 单工具独立 |

## 核心技术点

### 1. Agent Loop 循环机制

不同于单轮 Function Calling：

```python
# 单轮模式（原始）
response = llm.chat(messages)
if response.tool_calls:
    execute_tools()
    final_response = llm.chat(messages + tool_results)

# Agent Loop 模式（本作业）
while step < MAX_STEPS:
    response = llm.chat(messages)
    if not response.tool_calls:
        break  # 模型决定终止，给出最终答案
    execute_tools()
    messages.append(tool_results)  # 继续循环
```

### 2. 工具设计原则

- **单一职责**: 每个工具只做一件事
- **可组合性**: 工具输出能直接作为其他工具的输入
- **独立性**: 即使单独调用也能提供有价值的信息

### 3. Prompt Engineering

在工具 Schema 的 `description` 中明确说明：

- 何时单独使用该工具
- 如何与其他工具链式调用
- 参数格式和数据类型

## 文件结构

```
homework_split_weather/
├── weather_tools.py       # 业务逻辑层：两个工具的后端实现
├── run_agent.py          # Agent Loop 主程序
└── README.md             # 详细说明文档
```

## 快速开始

### 安装依赖

```bash
pip install openai httpx
```

### 配置 API Key

```bash
# Windows (PowerShell)
$env:DEEPSEEK_API_KEY="sk-xxx"

# Linux / macOS
export DEEPSEEK_API_KEY=sk-xxx
```

### 运行示例

```bash
# 单个问题
python homework_split_weather/run_agent.py -q "宁德今天的天气怎么样？"

# 内置示例（演示三种调用模式）
python homework_split_weather/run_agent.py --demo

# 切换 LLM 提供商
python homework_split_weather/run_agent.py --provider dashscope --demo
```

### 仅测试工具后端

```bash
python homework_split_weather/weather_tools.py
```

## 实现亮点

### 1. 同名城市消歧策略

继承自原 backend 的优化：

- 裸城市名如"宁德"可能匹配到小村庄
- 自动用"城市名+市"重查并优先采用高级行政区

### 2. LLM 无关的工具层

- `weather_tools.py` 纯 HTTP 调用，不依赖任何 LLM 库
- 可独立测试、独立部署
- 易于切换到其他 Agent 框架

### 3. 统计与可观测性

每次运行输出：

- 工具调用次数
- Agent Loop 循环轮数
- 总耗时

便于性能优化和调试

## 教学价值

### 对比单轮 Function Calling

| 特性 | 单轮模式 | Agent Loop |
|------|---------|-----------|
| 工具调用次数 | 固定1次 | 动态多次 |
| 复杂问题处理 | 需要预先组合工具 | LLM 自主规划 |
| 适用场景 | 简单查询 | 多步推理 |

### Agent 设计模式

1. **工具原子化**: 拆分而非聚合
2. **LLM 主导**: 由模型决定调用策略
3. **循环终止**: 模型自行判断何时给出最终答案

## 扩展方向

- [ ] 添加工具调用失败重试机制
- [ ] 支持并行工具调用
- [ ] 集成更多天气数据源（备份策略）
- [ ] 添加工具调用耗时监控

---

**完整代码和详细注释见 `homework_split_weather/` 目录。**
