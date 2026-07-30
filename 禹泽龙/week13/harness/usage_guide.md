# Harness 渐进式加载 Agent 框架使用指南

## 目录

- [概述](#概述)
- [项目结构](#项目结构)
- [核心设计思想](#核心设计思想)
- [框架流程详解](#框架流程详解)
- [Skill 规范](#skill-规范)
- [启动方式](#启动方式)
- [使用示例](#使用示例)
- [API 参考](#api-参考)
- [注意事项](#注意事项)
- [扩展指南](#扩展指南)

---

## 概述

Harness 是一个**渐进式加载**的 AI Agent 框架，灵感来自 Cursor、Claude Code 等工具的 skill 系统。

**核心能力：** 用户提问后，框架根据问题内容**动态匹配**相关 skill，加载其完整内容，再由大模型决定是否通过 `function_call` 调用具体脚本完成任务。

**与普通 Agent 的区别：**

| | 普通 Agent | Harness |
|---|---|---|
| 启动时 | 加载所有工具定义 | 只扫描 name + description |
| Skill 加载 | 全部预加载 | 按需懒加载 |
| 可扩展性 | 改代码 | 只需添加 skill 目录 |
| Function Call | 硬编码 | 由 SKILL.md 定义 |

---

## 项目结构

```
harness/                          # Harness 框架根目录
├── __init__.py                   # 包导出（对外接口）
├── skill.py                      # Skill 数据结构 + 懒加载逻辑
├── registry.py                   # Skill 注册表（启动时扫描）
├── agent.py                      # Agent 主类 + 对话循环 + 工具执行
├── example.py                    # 基础使用示例
└── usage_guide.md                # 本文档

skills/                           # Skill 集合目录（可自定义路径）
├── flash-card/
│   ├── SKILL.md                  # 必须：name/description + 文档 + function 定义
│   ├── scripts/
│   │   └── make_flashcard.py     # 实际执行逻辑的脚本
│   └── data/                     # 可选：数据存储目录
│       └── <word>.json
└── baoyu-diagram/
    ├── SKILL.md
    └── scripts/
        └── main.ts               # TypeScript 脚本（bun 运行）
```

---

## 核心设计思想

### 1. 渐进式加载（Lazy Loading）

```
启动时 ──────────────────────────────────────────────────────►
  │                                                        │
  ▼                                                        ▼
扫描 SKILL.md              用户提问时              LLM 决定
只读 frontmatter         匹配 + 加载完整内容        调用 tool
（name + description）                                │
                                                      ▼
                                               执行 skill 脚本
                                               返回 JSON 结果
```

**为什么这样做？**
- 启动速度极快（只读 YAML frontmatter，不解析完整文档）
- 支持大量 skills，按需加载，不浪费资源
- 大模型只在真正需要时才看到 skill 的完整定义

### 2. Function Call 绑定在 Skill 级别

每个 skill 在 `SKILL.md` 中通过 ```json 代码块声明 function schema，框架自动从已加载的 skill 中提取并注入 LLM。

### 3. 脚本执行标准化

Tool call 统一路由到 `skill/scripts/<script>`，通过 subprocess 调用：
- `.py` 文件 → `python <script>`
- `.ts` 文件 → `bun <script>` 或 `npx -y bun <script>`

---

## 框架流程详解

### 启动阶段

```
HarnessAgent.__init__()
  └─> SkillRegistry(skills_root)      # 扫描 skills/ 下所有 SKILL.md
       └─> _scan()
            └─> 对每个 skill_dir:
                 1. 读取 SKILL.md
                 2. 解析 frontmatter（只取 name + description）
                 3. 创建 Skill(name, description, path) 对象
                 4. 加入 _skills 字典
```

**此阶段不加载完整 SKILL.md 内容，不执行任何脚本。**

### 用户提问阶段

```
agent.prepare_skills_for_query(user_query)
  └─> registry.find_relevant_skills(query)
       └─> 根据关键词匹配（中文子串/英文分词）
            返回 top_k 个最相关的 Skill
  └─> 对每个 relevant skill: skill.load()
       └─> 读取完整 SKILL.md
            解析 frontmatter + headings + code_blocks
            提取 function definitions
```

### 对话循环阶段

```
agent.chat(user_message)
  │
  ├─► 第 1 轮：_call_llm()
  │    └─> 构建 messages
  │    └─> _build_functions()  ← 从已加载 skills 提取 function schema
  │    └─> llm_client.chat.completions.create(tools=[...])
  │    │
  │    ├─► 有 tool_calls → _execute_tool_calls()
  │    │    ├─> 根据 function name 找到对应 skill
  │    │    ├─> 路由到 skill/scripts/ 下脚本
  │    │    ├─> subprocess.run() 执行，传入 JSON 参数
  │    │    ├─> 返回 JSON 结果
  │    │    └─> 添加到 messages (role="tool")
  │    │    └─► 继续下一轮 _call_llm()
  │    │
  │    └─► 无 tool_calls → 返回 content，循环结束
  │
  └─► 第 N 轮：同上，直到无 tool_calls 或达到 max_turns
```

---

## Skill 规范

每个 skill 是一个目录，必须包含 `SKILL.md`。

### SKILL.md 结构

```yaml
---
name: <skill-name>           # 唯一标识，用作函数命名空间
description: >-              # 一句话描述，用于匹配用户问题
  <中文描述>
  Use when user says "...".
---

```json
[<function_schema>]         # function call 定义（必须）
```

# 标题

## 章节一

内容...
```

### frontmatter 必需字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | Skill 唯一名称，建议用 `kebab-case` |
| `description` | string | 描述匹配规则，中英文均可 |

### Function Schema 格式

SKILL.md 中用 ```json 代码块定义 function，框架会自动提取：

```json
[
  {
    "name": "function_name",          # 必填，函数唯一标识
    "description": "函数功能描述",     # 必填，大模型据此判断何时调用
    "parameters": {                   # 必填，JSON Schema 格式
      "type": "object",
      "properties": {
        "arg1": {
          "type": "string",
          "description": "参数说明"
        }
      },
      "required": ["arg1"]
    }
  }
]
```

### scripts/ 脚本规范

脚本通过 stdin 接收 JSON 参数，通过 stdout 返回 JSON 结果：

```python
# skill/scripts/run_xxx.py
import json, sys

args = json.load(sys.stdin)
# ... 执行逻辑 ...
result = {"status": "ok", "data": ...}
print(json.dumps(result))
```

```typescript
// skill/scripts/main.ts
const args = JSON.parse(await readAll stdin)
// ... 执行逻辑 ...
console.log(JSON.stringify(result))
```

---

## 启动方式

### 方式一：Python 代码调用

```python
from pathlib import Path
from harness import HarnessAgent, AgentConfig, get_chat_client

# 可选：手动传入 LLM client（否则自动从环境变量读取）
client, model = get_chat_client()

agent = HarnessAgent(
    skills_root=Path("."),          # 指向 skills/ 目录
    llm_client=client,
    model_name=model,
    config=AgentConfig(
        system_prompt="你是一个智能助手...",
        max_turns=10,
    ),
)

# 查看已注册的 skills
print(agent.list_all_skills())

# 用户提问
query = "给我做张 crazy 的闪卡"

# 预加载相关 skills（懒加载）
agent.prepare_skills_for_query(query)

# 进入对话循环
response = agent.chat(query)
print(response)
```

### 方式二：使用 example.py

```bash
cd harness/
python example.py
```

### 方式三：环境变量配置

```bash
# 选择 LLM Provider
export LLM_PROVIDER=deepseek        # 或 qwen
export DEEPSEEK_API_KEY=sk-xxx      # 或 DASHSCOPE_API_KEY

# 启动
python example.py
```

### 环境变量说明

| 变量 | 可选值 | 说明 |
|------|--------|------|
| `LLM_PROVIDER` | `deepseek`（默认）/ `qwen` | LLM 提供商 |
| `DEEPSEEK_API_KEY` | API Key | DeepSeek V4 Flash |
| `DASHSCOPE_API_KEY` | API Key | 阿里云 Qwen Plus |

---

## 使用示例

### 示例 1：生成英语闪卡

```python
agent.prepare_skills_for_query("给我做张 crazy 的闪卡")
response = agent.chat("给我做张 crazy 的闪卡")
```

**执行流程：**
1. `prepare_skills_for_query` 匹配到 `flash-card` skill 并加载
2. LLM 看到 `make_flashcard` function，调用它
3. 框架执行 `flash-card/scripts/make_flashcard.py`
4. JSON 数据保存到 `flash-card/data/crazy.json`
5. HTML 输出到当前目录 `crazy.html`
6. LLM 将文件路径返回给用户

### 示例 2：生成架构图

```python
agent.prepare_skills_for_query("画一个微服务架构图")
response = agent.chat("画一个微服务架构图")
```

**执行流程：**
1. 匹配到 `baoyu-diagram` skill 并加载
2. LLM 调用 `create_diagram` function（传入 SVG 内容）
3. 框架执行 `baoyu-diagram/scripts/main.ts`
4. SVG 保存到 `diagram/microservices-arch/xxx.svg`
5. PNG 保存到 `diagram/microservices-arch/xxx@2x.png`
6. LLM 将文件路径返回给用户

---

## API 参考

### HarnessAgent

```python
HarnessAgent(
    skills_root: str | Path,
    llm_client=None,        # 不传则自动从环境变量初始化
    model_name="",
    config: AgentConfig | None = None,
)
```

**方法：**

| 方法 | 说明 |
|------|------|
| `chat(message: str) -> str` | 处理用户消息，返回最终回答 |
| `prepare_skills_for_query(query: str)` | 根据问题预加载相关 skills |
| `list_all_skills() -> list[dict]` | 返回所有 skill 的 name + description |

### AgentConfig

```python
AgentConfig(
    system_prompt: str = "你是一个 AI 助手...",
    max_turns: int = 10,
)
```

### SkillRegistry

```python
registry = SkillRegistry(skills_root: str | Path)
registry.list_skills()              # 不加载，返回所有 Skill 对象
registry.get_skill(name: str)       # 获取指定 skill
registry.find_relevant_skills(query: str, top_k=3)  # 匹配相关 skills
```

### Skill（懒加载）

```python
skill: Skill = registry.get_skill("flash-card")
skill.load()                        # 手动触发加载完整内容
skill.is_loaded                     # 是否已加载
skill.load()                        # 返回 {"frontmatter": ..., "headings": ..., "code_blocks": ...}
```

---

## 注意事项

### 1. SKILL.md 必须有 frontmatter

```yaml
---
name: skill-name
description: 一句话描述
---
```

没有 frontmatter 或没有 `name` 字段的目录会被跳过。

### 2. Function Schema 必须放在 ```json 代码块中

框架通过识别 ```json 块来提取 function 定义。注意是 **```json**（不是 ```python 或其他语言）。

### 3. 脚本必须输出 JSON 到 stdout

脚本执行结果通过 stdout 返回，框架尝试解析为 JSON。如果脚本输出非 JSON 内容，会被包装为 `{"output": "..."}`。

### 4. 脚本超时

Python 脚本超时 120 秒，TypeScript 脚本同样。耗时操作建议在脚本内部做成分步执行或加长超时。

### 5. 中文匹配

`find_relevant_skills` 对中文使用**子串匹配 + 二元组**计分，英文使用**分词匹配**。如果匹配不准确，可以：
- 在 description 中包含更多中文关键词
- 或后续接入 embedding 做更精准的语义匹配

### 6. Skill 脚本路径查找顺序

```
skill/scripts/
  ├── <function_name>.py      # 先按 function name 查找
  ├── run_<function_name>.py  # 再按 run_ 前缀查找
  ├── main.py                 # 再找 main.py
  └── main.ts                 # 再找 main.ts
```

### 7. TypeScript Skill 需要 bun 环境

`baoyu-diagram` 是 TypeScript skill，需要：
- 安装 `bun`：https://bun.sh
- 或确保 `npx` 可用（框架会用 `npx -y bun` 替代）

### 8. 多 Tool Call 并行

同一轮 LLM 可能返回多个 tool_calls，框架会**串行执行**（一个完成后再执行下一个），结果按顺序添加回对话。

---

## 扩展指南

### 添加新 Skill

1. 在 `skills/` 下创建目录，例如 `my-skill/`
2. 创建 `SKILL.md`，包含 frontmatter + function schema
3. 可选创建 `scripts/` 目录，放入执行脚本
4. 重启 Agent，新 skill 自动被扫描注册

### 自定义 LLM Client

```python
from some_llm import CustomClient

client = CustomClient(...)  # 只要有 chat.completions.create 接口即可
agent = HarnessAgent(
    skills_root=Path("."),
    llm_client=client,
    model_name="my-model",
)
```

### 自定义 Tool 执行逻辑

重写 `HarnessAgent._execute_skill_function()` 方法：

```python
class MyAgent(HarnessAgent):
    def _execute_skill_function(self, skill, fn_name, args):
        # 自定义逻辑，比如改为 HTTP 调用
        return {"custom": "result"}
```

### 接入 Embedding 匹配

替换 `SkillRegistry.find_relevant_skills()` 的实现：

```python
def find_relevant_skills(self, query: str, top_k: int = 3) -> list[Skill]:
    # 1. 用 embedding model 将 query 和所有 description 向量化
    # 2. 计算余弦相似度
    # 3. 返回 top_k
```

---

## 快速参考

```bash
# 查看已注册 skills（不加载完整内容）
python -c "from harness import SkillRegistry; [print(s.name, s.description[:50]) for s in SkillRegistry('.').list_skills()]"

# 测试某个 skill 的 function 是否被正确提取
python -c "
from harness import SkillRegistry, extract_functions_from_skill
r = SkillRegistry('.')
s = r.get_skill('flash-card')
s.load()
print(extract_functions_from_skill(s))
"
```
