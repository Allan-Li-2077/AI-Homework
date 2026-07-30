# ReAct AI Tech Agent — AI面试技术问答系统

> 基于 ReAct（Reasoning + Acting）范式构建的 AI 技术问答智能体，支持手写 Prompt 解析和 Function Calling 两种实现方式，具备多轮对话能力。

---

## 目录

1. [项目背景与目标](#1-项目背景与目标)
2. [实用工具说明](#2-实用工具说明)
3. [项目结构](#3-项目结构)
4. [环境配置](#4-环境配置)
5. [完整实验流程](#5-完整实验流程)
6. [各方案原理简介](#6-各方案原理简介)
7. [实验执行过程与日志](#7-实验执行过程与日志)
8. [评估结果汇总](#8-评估结果汇总)
9. [结果分析与讨论](#9-结果分析与讨论)
10. [最终结论](#10-最终结论)
11. [产出文件索引](#11-产出文件索引)
12. [常见问题](#12-常见问题)
13. [附录：企业级落地方案](#13-附录企业级落地方案)
14. [附录：技术细节](#14-附录技术细节)

---

## 1. 项目背景与目标

### 1.1 项目背景

本项目基于 **ReAct（Reasoning + Acting）** 范式，构建一个面向 AI 技术面试场景的智能问答系统。通过引入外部工具（概念查询、论文检索、计算器等），使大语言模型能够在推理过程中主动调用工具获取准确信息，避免幻觉问题。

### 1.2 核心目标

| 目标 | 描述 |
|------|------|
| **ReAct 范式落地** | 实现 Thought → Action → Observation 循环，推理与行动交替驱动 |
| **两种实现对比** | 对比手写 Prompt 解析与 Function Calling API 的优缺点 |
| **多轮对话支持** | 支持上下文理解，实现自然流畅的多轮问答 |
| **AI 技术问答** | 聚焦 AI 技术面试场景，涵盖概念定义、论文解读、技术对比等 |
| **教学价值** | 提供清晰的代码结构和运行日志，便于学习和理解 |

### 1.3 应用场景

- **AI 技术面试准备**：模拟真实面试场景，练习技术问答
- **技术学习辅助**：查询 AI 概念、阅读论文摘要、对比技术差异
- **知识库问答**：基于已有的论文向量库进行语义检索
- **Agent 开发学习**：学习 ReAct 范式的工程实现

---

## 2. 实用工具说明

系统内置 5 个工具，覆盖 AI 技术问答的核心需求：

| 工具名 | 数据来源 | 核心用途 | 典型参数 |
|--------|---------|---------|---------|
| `ai_concept_lookup` | 静态字典 | AI 概念定义查询，防幻觉 | `name="Transformer"` |
| `rag_search` | FAISS + DashScope Embedding | AI 论文语义检索 | `query="注意力机制原理"` |
| `paper_summary` | FAISS + DashScope Embedding | 论文摘要检索 | `title="Attention Is All You Need"` |
| `concept_compare` | 静态字典 | 两个 AI 概念对比 | `concept1="Transformer"`, `concept2="RNN"` |
| `calculator` | Python eval（受限沙箱） | 数学计算 | `expr="512 * 512"` |

### 2.1 工具调用示例

```python
from tools import TOOLS_MAP

# AI 概念查询
TOOLS_MAP["ai_concept_lookup"](name="Transformer")

# 论文检索
TOOLS_MAP["rag_search"](query="注意力机制原理", top_k=3)

# 概念对比
TOOLS_MAP["concept_compare"](concept1="Transformer", concept2="RNN")
```

---

## 3. 项目结构

```
ai_tech_interview_agent/
├── src/                              # 源代码目录
│   ├── tools.py                      # 5 个工具实现（核心）
│   ├── react_manual.py               # 手写 Prompt 解析版 ReAct
│   ├── react_function_calling.py     # Function Calling 版 ReAct
│   ├── agent.py                      # 统一命令行入口
│   ├── serve.py                      # FastAPI HTTP 服务（支持多轮对话）
│   └── evaluate.py                   # 两种实现对比评估
├── vectorstore/                      # 向量数据库
│   ├── faiss_index.bin               # FAISS 索引（1024维，~10000+条）
│   └── faiss_meta.json               # 向量对应的 chunk 元数据
├── models/                           # 本地模型（可选）
│   └── bge-small-zh-v1.5/            # 本地 Embedding 模型（512维，当前未使用）
├── index.html                        # Web UI，聊天式多轮对话界面
├── ARCHITECTURE.md                   # 技术方案文档
├── USAGE_GUIDE.md                    # 使用指南
├── requirements.txt                  # 依赖列表
└── README.md                         # 本文件
```

---

## 4. 环境配置

### 4.1 安装依赖

```bash
pip install openai faiss-cpu fastapi uvicorn numpy
```

### 4.2 配置 API Key

**Linux / macOS：**
```bash
export DASHSCOPE_API_KEY="sk-xxx"       # 必填，用于 LLM 推理和 RAG Embedding
export AGENT_MODEL="qwen-max"           # 可选，默认 qwen-max
```

**Windows PowerShell：**
```powershell
$env:DASHSCOPE_API_KEY = "sk-xxx"
$env:AGENT_MODEL = "qwen-max"
```

### 4.3 获取 API Key

1. 访问 [阿里云 DashScope 控制台](https://dashscope.console.aliyun.com/)
2. 登录阿里云账号（需要实名认证）
3. 在 API Key 管理页面创建或查看你的 API Key

### 4.4 虚拟环境配置（推荐）

```powershell
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
& .venv\Scripts\Activate.ps1

# 安装依赖
pip install openai faiss-cpu fastapi uvicorn numpy
```

---

## 5. 完整实验流程

### 5.1 流程概览

```
Step 1: 环境准备
    │
    ├── 安装依赖
    ├── 配置 API Key
    └── 启动虚拟环境
    │
Step 2: 命令行测试
    │
    ├── agent.py (手动模式)
    ├── react_manual.py
    └── react_function_calling.py
    │
Step 3: 对比评估
    │
    └── evaluate.py
    │
Step 4: Web 服务
    │
    └── serve.py + index.html
    │
Step 5: 多轮对话体验
    │
    └── 在 Web UI 中进行多轮问答
```

### 5.2 详细步骤

**步骤 1：启动虚拟环境**
```powershell
cd E:\AI课学习\week12 agent\ai_tech_interview_agent
& .venv\Scripts\Activate.ps1
$env:DASHSCOPE_API_KEY = "sk-xxx"
```

**步骤 2：命令行测试（手写版）**
```powershell
cd src
python agent.py --mode manual --question "Transformer和RNN的主要区别是什么？"
```

**步骤 3：命令行测试（Function Calling 版）**
```powershell
python agent.py --mode fc --question "BERT和GPT有什么区别？"
```

**步骤 4：运行评估脚本**
```powershell
python evaluate.py
```

**步骤 5：启动 Web 服务**
```powershell
python -m uvicorn serve:app --host 0.0.0.0 --port 8000
```

**步骤 6：访问 Web UI**
- 打开浏览器访问：http://localhost:8000
- 体验多轮对话功能

---

## 6. 各方案原理简介

### 6.1 ReAct 范式核心原理

ReAct（Reasoning + Acting）是一种让大语言模型在推理过程中主动与外部工具交互的范式：

```
┌─────────────────────────────────────────────────────┐
│               ReAct 循环（最多 10 步）               │
│                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐   │
│  │  Thought  │──▶│  Action  │──▶│ Observation  │   │
│  │ LLM 推理  │   │ 工具调用  │   │  工具返回结果  │   │
│  └──────────┘   └──────────┘   └──────┬───────┘   │
│       ▲                                │           │
│       └────────────────────────────────┘           │
│                      循环                           │
└─────────────────────────────────────────────────────┘
    │ Final Answer
    ▼
用户回答
```

### 6.2 手写 Prompt 解析版

**原理**：通过 System Prompt 约束模型输出格式，使用正则表达式解析模型输出。

```python
# System Prompt 格式约束
"""
Thought: 分析当前状态...
Action: 工具名称
Action Input: {"参数名": "参数值"}
"""

# 正则解析
_THOUGHT_RE      = re.compile(r"Thought:\s*(.+?)(?=\nAction:|\nFinal Answer:|$)", re.DOTALL)
_ACTION_RE       = re.compile(r"Action:\s*(\w+)")
_ACTION_INPUT_RE = re.compile(r"Action Input:\s*(\{.+?\})", re.DOTALL)
_FINAL_RE        = re.compile(r"Final Answer:\s*(.+)", re.DOTALL)
```

**优点**：Thought 完全可见，每步透明，适合教学
**缺点**：模型偶尔输出格式不规范，需要容忍解析错误

### 6.3 Function Calling 版

**原理**：通过 JSON Schema 将工具注册给模型，模型原生理解参数结构。

```python
# 工具注册
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "ai_concept_lookup",
            "description": "查询 AI 概念定义",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "概念名称"}
                },
                "required": ["name"]
            }
        }
    }
]

# 循环判断
if reason == "stop" or not msg.tool_calls:
    # 模型决定直接回答，循环结束
else:
    # 执行 tool_calls，追加 tool 角色消息继续
```

**优点**：格式稳定，代码量少，适合生产环境
**缺点**：Thought 在模型内部不可见

### 6.4 多轮对话机制

通过 `conversation_history` 参数传递历史对话：

```python
conversation_history = [
    {"question": "Transformer是什么？", "answer": "Transformer是..."},
    {"question": "它的注意力机制是怎样的？", "answer": "注意力机制..."}
]
```

在每次调用时，历史对话会被追加到消息列表中，使模型能够理解上下文。

---

## 7. 实验执行过程与日志

### 7.1 命令行测试日志示例

**手写版（react_manual.py）**：
```
============================================================
问题: Transformer和RNN的主要区别是什么？
模型: qwen-max  实现: 手写Prompt解析
============================================================

[Step 1]
🧠 Thought: 需要对比Transformer和RNN两个概念的差异
🔧 Action:  concept_compare
   Input:   {"concept1": "Transformer", "concept2": "RNN"}
👁  Obs:     【Transformer】
   类型: 架构 | 年份: 2017
   描述: 基于注意力机制的序列建模架构...
   【RNN】
   类型: 架构 | 年份: 1982
   描述: 循环神经网络...
   【对比分析】
   ✓ 同类型概念
   ✗ 年份不同：2017 vs 1982
   差异关键点: LSTM/GRU变体、自注意力机制...

✅ Final Answer:
Transformer与RNN在处理序列数据时采用了完全不同的方法...
```

**Function Calling 版（react_function_calling.py）**：
```
============================================================
问题: BERT和GPT有什么区别？
模型: qwen-max  实现: Function Calling
============================================================

[Step 1]
🔧 Action:  concept_compare
   Input:   {"concept1": "BERT", "concept2": "GPT"}
👁  Obs:     【BERT】...【GPT】...【对比分析】...

✅ Final Answer:
BERT和GPT的主要区别在于训练方式和应用场景...
```

### 7.2 Web UI 测试

启动服务后访问 http://localhost:8000，可观察到完整的聊天式对话界面：

**界面布局：**
```
┌─────────────────────────────────────────────────────┐
│ ⚡ ReAct AI Tech Agent                              │
│ Thought → Action → Observation 循环演示              │
├─────────────────────────────────────────────────────┤
│ [手写 Prompt 解析] [Function Calling] 对话轮次: 0    │
├─────────────────────────────────────────────────────┤
│ 👋 你好！我是 AI 技术问答助手...                     │
│                                                     │
│ 用户: Transformer和RNN的主要区别是什么？            │
│ AI:    🤔 正在思考...                              │
│        ✅ Final Answer: Transformer与RNN在处理...   │
│        🔧 ReAct 思考过程 (1 步) ▼                   │
│                                                     │
│ 用户: 它的注意力机制是怎样工作的？                   │
│ AI:    ...                                         │
├─────────────────────────────────────────────────────┤
│ [输入框] [清空对话] [发送]                           │
│ 快速提问: [示例1] [示例2] [示例3]                   │
└─────────────────────────────────────────────────────┘
```

**实际运行截图示例：**

**第1轮对话：**
```
用户: Transformer和RNN的主要区别是什么？

AI思考过程：
  Step 1: concept_compare("Transformer", "RNN")
  Obs: 【Transformer】类型: 架构 | 年份: 2017 | 描述: 基于注意力机制...
       【RNN】类型: 架构 | 年份: 1982 | 描述: 循环神经网络...
       【对比分析】同类型概念，年份不同，差异关键点: LSTM/GRU变体、自注意力机制...

Final Answer:
Transformer与RNN在处理序列数据时采用了完全不同的方法。RNN通过其内部状态来保持时间上的信息...
相比之下，Transformer模型则摒弃了传统意义上的递归结构，转而使用自注意力机制...
```

**第2轮对话（多轮上下文）：**
```
用户: 它的注意力机制是怎样工作的？

AI思考过程：
  Step 1: rag_search("注意力机制原理")
  Obs: [1] 来源：Attention Is All You Need (2017) 第1页
       内容：The attention mechanism computes a weighted sum of the values...

Final Answer:
注意力机制通过计算查询向量与键向量的相似度来确定每个值向量的权重...
```

**界面功能特点：**
1. **聊天式对话界面**：紫色用户气泡 + 灰色 AI 气泡，类似 ChatGPT
2. **思考中动画**：🤔 正在思考... + 打字指示器
3. **可折叠的 ReAct 思考过程**：点击展开/折叠详细步骤
4. **实时对话轮次显示**：右上角显示当前对话轮数
5. **多轮对话上下文保持**：自动保存历史，支持代词指代理解
6. **清空对话按钮**：一键清除所有历史记录
7. **快速提问示例**：点击即可填入输入框
8. **实现方式切换**：支持手写 Prompt 解析 / Function Calling 切换

---

## 8. 评估结果汇总

### 8.1 评估问题集

| ID | 问题类型 | 问题描述 |
|----|---------|---------|
| Q1 | 概念对比 | Transformer 和 RNN 的主要区别是什么？ |
| Q2 | 论文摘要 | Attention Is All You Need 论文的核心贡献是什么？ |
| Q3 | 概念查询 | BERT 模型的关键技术点有哪些？ |
| Q4 | 论文细节 | 多头注意力机制是如何工作的？ |
| Q5 | 边界拒绝 | 预测未来十年 AI 的发展方向（应拒绝） |

### 8.2 评估结果（实际运行数据）

| ID | 模式 | 步数 | 耗时(s) | 成功 | 解析错误 | 工具调用链 |
|----|------|------|---------|------|---------|-----------|
| Q1 | manual | 1 | ~8.2 | ✅ | 0 | concept_compare |
| Q1 | fc | 1 | ~8.3 | ✅ | 0 | concept_compare |
| Q2 | manual | 3 | ~16.6 | ✅ | 0 | paper_summary → rag_search → 总结 |
| Q2 | fc | 1 | ~7.3 | ✅ | 0 | paper_summary |
| Q3 | manual | 1 | ~7.9 | ✅ | 0 | ai_concept_lookup |
| Q3 | fc | 1 | ~30.3 | ✅ | 0 | ai_concept_lookup |
| Q4 | manual | 4 | ~20.5 | ✅ | 0 | rag_search × 2 → ai_concept_lookup → 总结 |
| Q4 | fc | 2 | ~17.4 | ✅ | 0 | rag_search → ai_concept_lookup |
| Q5 | manual | 1 | ~16.9 | ✅ | 0 | 直接拒绝（无工具调用） |
| Q5 | fc | 0 | ~16.8 | ✅ | 0 | 直接拒绝（无工具调用） |

### 8.3 统计汇总

| 模式 | 平均步数 | 平均耗时 | 成功率 | 解析错误总数 |
|------|---------|---------|--------|-------------|
| manual | 2.0 | 14.0s | 100% | 0 |
| fc | 1.2 | 15.0s | 100% | 0 |

### 8.4 Web UI 实际运行效果验证

**验证项**：

| 验证点 | 结果 | 说明 |
|--------|------|------|
| 网页加载 | ✅ | 正常打开，界面渲染完整 |
| 模式切换 | ✅ | 手写 Prompt 解析 / Function Calling 切换正常 |
| 问题发送 | ✅ | 点击发送或 Enter 键均可提交 |
| 思考中动画 | ✅ | 🤔 正在思考... + 打字指示器正常显示 |
| 工具调用展示 | ✅ | ReAct 思考过程折叠/展开正常 |
| 答案展示 | ✅ | Final Answer 完整显示 |
| 多轮对话 | ✅ | 上下文保持良好，"它"等代词可正确理解 |
| 清空对话 | ✅ | 一键清除历史记录正常 |
| 快速提问 | ✅ | 点击示例可自动填入输入框 |

**多轮对话实际测试案例**：

```
第1轮：
用户: Transformer是什么？
AI回答: Transformer是一种基于注意力机制的序列建模架构，由Google在2017年提出...

第2轮（上下文理解）：
用户: 它的核心创新是什么？
AI回答: Transformer的核心创新在于引入了自注意力机制，能够并行化处理序列数据...
（成功理解"它"指代Transformer）

第3轮（深入追问）：
用户: 多头注意力和普通注意力有什么区别？
AI回答: 多头注意力通过多个注意力头并行计算...
（成功基于前两轮对话继续深入）
```

---

## 9. 结果分析与讨论

### 9.1 两种实现对比

| 维度 | 手写 Prompt 解析 | Function Calling API |
|------|----------------|----------------------|
| Thought 可见性 | 完全可见，正则解析 | 模型内部，不可见 |
| 格式稳定性 | 依赖 Prompt 工程，偶有漂移 | 原生结构化，格式稳定 |
| 代码量 | ~150 行核心逻辑 | ~80 行核心逻辑 |
| 可控性 | 高，可定制停止词和格式 | 低，依赖模型实现 |
| 教学价值 | 高，学生能看见每一步 | 次之，适合生产场景 |
| 平均步数 | 2.0 | 1.2 |
| 平均耗时 | 14.0s | 15.0s |

### 9.2 多轮对话效果

多轮对话功能表现优秀，通过实际测试验证：

**测试案例1：代词指代理解**
```
第1轮: 用户: Transformer是什么？
       AI:    Transformer是一种基于注意力机制的序列建模架构...

第2轮: 用户: 它的核心创新是什么？
       AI:    Transformer的核心创新在于引入了自注意力机制...
```
✅ 成功理解"它"指代Transformer

**测试案例2：上下文延续**
```
第1轮: 用户: BERT和GPT有什么区别？
       AI:    BERT是双向预训练模型，GPT是单向自回归模型...

第2轮: 用户: 哪个更适合做问答任务？
       AI:    BERT更适合问答任务，因为其双向注意力机制...
```
✅ 成功基于历史回答继续讨论

**测试案例3：深度追问**
```
第1轮: 用户: 什么是注意力机制？
       AI:    注意力机制通过计算查询、键、值的相似度来加权求和...

第2轮: 用户: 具体怎么计算的？
       AI:    注意力机制的计算包括：1.计算相似度得分...

第3轮: 用户: 为什么需要缩放因子？
       AI:    缩放因子可以防止内积过大导致梯度消失...
```
✅ 支持连续深度追问，逻辑连贯

**多轮对话技术实现**：
- 前端：`conversationHistory` 数组存储历史对话，每次发送时传递给后端
- 后端：`conversation_history` 参数追加到消息列表，使模型理解上下文
- 清空：支持一键清除历史，重新开始对话

**对话轮次限制**：
- 理论上无限制，但受模型上下文窗口限制（qwen-max 支持 128K token）
- 实际测试中连续 5-10 轮对话效果良好

### 9.3 边界情况处理

- **Q5（预测未来）**：模型正确识别出这是无法回答的问题，拒绝回答
- **格式漂移**：手写版能够容忍部分格式不规范的输出
- **工具调用失败**：系统有错误处理机制，不会导致程序崩溃

---

## 10. 最终结论

### 10.1 项目成果

经过完整的功能测试和评估，项目取得以下成果：

1. ✅ **成功实现 ReAct 范式**：两种实现方式（手写 Prompt 解析、Function Calling）均能正确执行 Thought → Action → Observation 循环，评估成功率 100%

2. ✅ **多轮对话能力**：Web UI 和 API 均支持多轮对话，上下文保持良好，成功验证了代词指代理解、上下文延续和深度追问能力

3. ✅ **工具集完整**：5 个工具（`ai_concept_lookup`、`rag_search`、`paper_summary`、`concept_compare`、`calculator`）覆盖 AI 技术问答的核心需求

4. ✅ **聊天式 Web UI**：美观的对话界面，支持思考过程折叠/展开、思考中动画、清空对话、快速提问等功能

5. ✅ **教学价值高**：代码结构清晰，日志输出详细，便于学习 ReAct 范式的工程实现

6. ✅ **评估结果优秀**：100% 成功率，解析错误为 0，平均耗时在可接受范围内

### 10.2 实际运行总结

**Web UI 运行效果**：
- 界面加载：正常，无报错
- 多轮对话：流畅，上下文保持良好
- 工具调用：正确，ReAct 思考过程清晰可见
- 响应速度：平均 8-20 秒/轮（受网络和模型推理时间影响）

**命令行运行效果**：
- 手写版：Thought 完全可见，教学效果好
- FC 版：格式稳定，代码量少

### 10.3 技术选型建议

| 场景 | 推荐方案 | 理由 |
|------|---------|------|
| 教学演示 | 手写 Prompt 解析 | Thought 可见，每步透明 |
| 生产环境 | Function Calling | 格式稳定，代码量少 |
| 快速原型 | Function Calling | 开发效率高 |
| 定制化需求 | 手写 Prompt 解析 | 可控性高，可定制停止词和格式 |

### 10.4 项目价值

- **学习价值**：通过实际代码理解 ReAct 范式的工作原理
- **应用价值**：可作为 AI 技术面试准备工具
- **扩展价值**：代码结构清晰，易于扩展新工具和功能
- **教学价值**：提供完整的实验流程和评估体系

---

## 11. 产出文件索引

| 文件 | 说明 |
|------|------|
| [src/tools.py](file:///E:/AI课学习/week12%20agent/ai_tech_interview_agent/src/tools.py) | 5 个工具实现 |
| [src/react_manual.py](file:///E:/AI课学习/week12%20agent/ai_tech_interview_agent/src/react_manual.py) | 手写 Prompt 解析版 ReAct |
| [src/react_function_calling.py](file:///E:/AI课学习/week12%20agent/ai_tech_interview_agent/src/react_function_calling.py) | Function Calling 版 ReAct |
| [src/agent.py](file:///E:/AI课学习/week12%20agent/ai_tech_interview_agent/src/agent.py) | 统一命令行入口 |
| [src/serve.py](file:///E:/AI课学习/week12%20agent/ai_tech_interview_agent/src/serve.py) | FastAPI HTTP 服务 |
| [src/evaluate.py](file:///E:/AI课学习/week12%20agent/ai_tech_interview_agent/src/evaluate.py) | 对比评估脚本 |
| [index.html](file:///E:/AI课学习/week12%20agent/ai_tech_interview_agent/index.html) | Web UI |
| [vectorstore/faiss_index.bin](file:///E:/AI课学习/week12%20agent/ai_tech_interview_agent/vectorstore/faiss_index.bin) | FAISS 向量索引 |
| [vectorstore/faiss_meta.json](file:///E:/AI课学习/week12%20agent/ai_tech_interview_agent/vectorstore/faiss_meta.json) | 向量元数据 |
| [ARCHITECTURE.md](file:///E:/AI课学习/week12%20agent/ai_tech_interview_agent/ARCHITECTURE.md) | 技术方案文档 |
| [USAGE_GUIDE.md](file:///E:/AI课学习/week12%20agent/ai_tech_interview_agent/USAGE_GUIDE.md) | 使用指南 |

---

## 12. 常见问题

### Q: `rag_search` 报错 `assert d == self.d`

**原因**：Embedding 维度不匹配。FAISS 索引使用 DashScope `text-embedding-v3`（1024维）构建，而本地 `bge-small-zh-v1.5` 是 512 维。

**解决**：确保 `DASHSCOPE_API_KEY` 已正确设置，`rag_search` 会自动使用 DashScope API 进行编码，保持 1024 维一致。

### Q: Web UI 显示"请求失败"

**解决**：
1. 检查 `uvicorn` 是否正常启动
2. 访问 `http://localhost:8000/health` 确认服务状态
3. 检查 `DASHSCOPE_API_KEY` 是否正确配置

### Q: 手写版 Thought 为空

**原因**：qwen-max 在部分中间步骤会省略 Thought 直接输出 Action。

**说明**：这是正常现象，解析器已做容错处理，不影响工具执行和最终结果。

### Q: 控制台显示 `net::ERR_ABORTED`

**原因**：浏览器在页面刷新或导航时中止了未完成的请求。

**说明**：这是浏览器的正常行为，不影响问答功能。系统已添加 `AbortController` 进行优雅处理。

### Q: 如何使用 DeepSeek-V3 模型

```powershell
$env:DASHSCOPE_API_KEY = "sk-xxx"   # DashScope key 可用于 DeepSeek
$env:AGENT_MODEL = "deepseek-v3"
```

---

## 13. 附录：企业级落地方案

### 13.1 架构建议

```
┌─────────────────────────────────────────────────────────┐
│                      客户端                              │
│              Web UI / 移动端 / API 调用                   │
└──────────────────┬──────────────────────────────────────┘
                   │ HTTP/gRPC
                   ▼
┌─────────────────────────────────────────────────────────┐
│                    API Gateway                           │
│           负载均衡 / 限流 / 认证 / 日志                    │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│                    Agent 服务                            │
│          ReAct 循环 / 工具调用 / 对话管理                   │
└──────────────────┬──────────────────────────────────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
┌─────────────────┐  ┌─────────────────┐
│    LLM 服务      │  │   向量数据库      │
│  Qwen / DeepSeek │  │   FAISS / Milvus │
└─────────────────┘  └─────────────────┘
```

### 13.2 关键优化点

| 优化项 | 建议方案 |
|--------|---------|
| **对话存储** | 使用 Redis 存储对话历史，支持分布式部署 |
| **缓存机制** | 缓存工具调用结果，减少重复计算 |
| **限流控制** | API Gateway 层实现速率限制 |
| **监控告警** | 接入 Prometheus + Grafana 监控 |
| **日志系统** | ELK Stack 集中管理日志 |
| **模型切换** | 支持多模型切换，AB 测试 |
| **安全性** | 工具调用参数校验，防止注入攻击 |

### 13.3 扩展方向

1. **知识库扩展**：增加更多 AI 论文和技术文档
2. **工具扩展**：添加代码解释、技术博客检索等工具
3. **多模态支持**：支持图片、语音输入输出
4. **个性化推荐**：根据用户历史推荐相关问题
5. **面试模拟**：模拟真实面试场景，打分评价

---

## 14. 附录：技术细节

### 14.1 RAG 索引构建流程

```
1. 收集 AI 技术论文（PDF/TXT）
2. 文本分段（chunk size: 512 tokens）
3. 使用 DashScope text-embedding-v3 编码（1024维）
4. 构建 FAISS IndexFlatIP 索引
5. 保存索引和元数据到 vectorstore/
```

### 14.2 流式输出实现

使用 Server-Sent Events（SSE）实现实时推送：

```python
# SSE 事件格式
yield f"data: {{\"type\": \"action\", \"step\": {step}, ...}}\n\n"
yield f"data: {{\"type\": \"final\", \"answer\": \"{answer}\"}}\n\n"
```

### 14.3 Windows 兼容性处理

```python
# 解决 OpenMP 冲突
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
```

---

## 版本信息

- **项目版本**：v1.0
- **模型版本**：Qwen-Max（默认）
- **向量索引版本**：1024维（DashScope text-embedding-v3）
- **最后更新**：2026-07-22

---

## License

本项目仅供学习和研究使用。
