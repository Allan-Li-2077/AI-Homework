# Week 12 - ReAct Agent 多轮对话扩展

## 作业概述

本周作业在 Week 11 的 Function Calling 基础上，实现了**多轮对话能力**。通过持久化对话历史，Agent 能够记住之前的查询结果，支持用户基于上下文进行追问和深入分析。

## 核心改进

### 从单轮到多轮的关键变化

```python
# 原始单轮模式
def run(question):
    messages = [system_prompt, user_message]
    # ... 工具调用循环
    return final_answer

# 多轮对话模式（本作业）
class ChatAgent:
    def __init__(self):
        self.messages = [system_prompt]  # 持久化历史
    
    def chat(self, user_input):
        self.messages.append(user_message)
        # ... 工具调用循环
        self.messages.append(assistant_answer)  # 结果写回历史
```

### 关键设计点

1. **对话记忆持久化**  
   `messages` 从局部变量提升为实例属性，跨轮次保留

2. **单轮 ReAct 循环不变**  
   每轮用户输入仍然走完整的 Tool → Observation → Answer 流程

3. **上下文累积**  
   每轮的工具调用结果和最终回答都成为下一轮的背景知识

## 应用场景示例

### 场景 1: 数据查询 + 计算分析

```
用户: 查一下比亚迪的市盈率
Agent: [调用工具] 市盈率是 25.3

用户: 和行业平均值比怎么样？
Agent: [基于上轮数据] 行业平均 32.1，比亚迪低于平均水平...
```

### 场景 2: 多维度对比

```
用户: 比较宁德时代和亿纬锂能的营收
Agent: [调用工具] 宁德时代 XXX 亿，亿纬锂能 YYY 亿

用户: 再看看毛利率
Agent: [继续分析，无需重新查公司代码]
```

## 技术实现

### 1. ChatAgent 类设计

```python
class ChatAgent:
    def __init__(self, max_steps: int = 10):
        self.max_steps = max_steps
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    def chat(self, user_input: str):
        """处理一轮用户输入，保留历史"""
        self.messages.append({"role": "user", "content": user_input})
        # ... Agent Loop
        self.messages.append({"role": "assistant", "content": answer})
    
    def reset(self):
        """清空对话历史（可选）"""
        self.messages = [self.messages[0]]  # 保留 system prompt
```

### 2. 命令行交互界面 (REPL)

```python
while True:
    question = input("\n你: ").strip()
    if question in ("exit", "quit"):
        break
    if question == "reset":
        agent.reset()
        continue
    chat_and_print(agent, question)
```

### 3. 支持的命令

- **正常提问**: 直接输入问题
- **`exit` / `quit`**: 退出程序
- **`reset`**: 清空对话历史，重新开始

## 快速开始

### 依赖安装

```bash
pip install openai faiss-cpu sentence-transformers akshare
```

### 配置环境

```bash
# Windows (PowerShell)
$env:DEEPSEEK_API_KEY="sk-xxx"

# Linux / macOS
export DEEPSEEK_API_KEY=sk-xxx
```

### 运行

```bash
# 默认配置
python react_function_calling_chat.py

# 自定义最大步数
python react_function_calling_chat.py --max_steps 8
```

## 文件说明

- **react_function_calling_chat.py**: 主程序，多轮对话 Agent
- **tools.py**: 工具集（需放在 src 目录下，见课程资料）
  - `company_lookup`: 公司名 → 股票代码
  - `financial_indicator`: 查询财务指标
  - `stock_price`: 查询股价
  - `calculator`: 数值计算

## 与 Week 11 的对比

| 特性 | Week 11 | Week 12 |
|------|---------|---------|
| 对话模式 | 单轮问答 | 多轮连续对话 |
| 历史记忆 | 无 | 完整保留 |
| 追问能力 | 不支持 | 支持上下文追问 |
| 适用场景 | 独立查询 | 数据分析、探索式调研 |

## 教学价值

### 1. 对话状态管理

展示了从无状态函数到有状态 Agent 的演进：

- 无状态: 每次调用独立，无法关联
- 有状态: 累积上下文，支持复杂交互

### 2. ReAct 模式的完整实现

- **R**easoning: 模型内部推理（Function Calling 版不可见）
- **A**cting: 调用工具获取信息
- **O**bserving: 处理工具返回结果
- **循环**: 直到问题解决

### 3. 生产级考虑

- 历史截断策略（防止 token 超限）
- 会话管理（多用户隔离）
- 状态持久化（数据库/缓存）

## 优化方向

- [ ] 历史消息自动摘要（避免 context 过长）
- [ ] 支持导出对话记录
- [ ] 添加工具使用统计
- [ ] 集成向量数据库（RAG 增强）

---

**注**: 完整工具实现 (`tools.py`) 见课上演示代码，需放置在 `src/` 目录下。
