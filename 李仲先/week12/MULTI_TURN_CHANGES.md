# 多轮对话功能改动总结

## 概述

为 ReAct 金融 Agent 增加了多轮对话能力，使 Agent 能够记住之前的对话历史，支持连续追问和上下文理解。

## 主要改动

### 1. `src/react_manual.py` - 手写 Prompt 解析版

**改动内容：**
- 修改 `run()` 函数签名，增加 `conversation_history` 可选参数
- 支持传入历史对话消息，将其添加到 LLM 的消息列表中
- 保持原有的 ReAct 循环逻辑不变

**关键代码：**
```python
def run(question: str, max_steps: int = 10, verbose: bool = True, conversation_history: list = None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": question})
    # ... 原有 ReAct 循环逻辑
```

### 2. `src/react_function_calling.py` - Function Calling 版

**改动内容：**
- 修改 `run()` 函数签名，增加 `conversation_history` 可选参数
- 与手写版保持一致的多轮对话支持

### 3. `src/serve.py` - FastAPI 后端服务

**新增功能：**

1. **会话管理类 `SessionData`**：
   - 使用 UUID 生成唯一会话 ID
   - 存储对话历史（`history` 列表）
   - 提供 `add_turn()` 和 `get_history()` 方法

2. **内存会话存储**：
   - 使用全局字典 `sessions` 存储会话（生产环境建议使用 Redis）
   - 提供 `get_or_create_session()` 工具函数

3. **新增 API 端点**：

   | 端点 | 方法 | 说明 |
   |------|------|------|
   | `/session/new` | POST | 创建新会话，返回 `session_id` |
   | `/session/{id}` | GET | 获取指定会话的历史记录 |
   | `/chat/manual` | POST | 手写版多轮对话（请求体包含 `session_id`） |
   | `/chat/fc` | POST | Function Calling 版多轮对话 |

4. **SSE 流式响应增强**：
   - 在 `done` 事件中包含 `final_answer` 字段
   - 响应头包含 `X-Session-Id` 用于前端跟踪会话
   - 自动保存对话历史到会话

**请求/响应模型：**
```python
class ChatRequest(BaseModel):
    question:    str
    session_id:  Optional[str] = None
    max_steps:   int = 10

class SessionResponse(BaseModel):
    session_id: str
    history:    list
    turn_count: int
```

### 4. `src/agent.py` - CLI 入口

**新增功能：**

1. **`--chat` 参数**：启用交互式多轮对话模式
2. **`run_chat()` 函数**：实现交互式对话循环
   - 支持连续提问，自动维护对话历史
   - 特殊命令：
     - `exit` / `quit`：退出对话
     - `/new`：清空对话历史
     - `/history`：查看对话历史

**使用方式：**
```bash
# 单次查询（原有功能）
python src/agent.py --mode manual --question "茅台2023年毛利率？"

# 多轮对话（新增）
python src/agent.py --chat
python src/agent.py --mode fc --chat
```

### 5. `index.html` - Web 前端

**新增功能：**

1. **会话管理 UI**：
   - 显示当前会话 ID
   - "新建会话" 按钮，可随时开始新对话

2. **对话历史显示**：
   - 在输入区上方显示历史对话
   - 用户消息和助手回答分别用不同样式展示
   - 支持连续追问，自动滚动到最新内容

3. **API 调用更新**：
   - 使用 `/chat/{mode}` 端点替代 `/query/{mode}`
   - 自动管理 `session_id`，在请求中传递
   - 从响应头获取最新的 `session_id`

4. **UI 样式**：
   - 新增 `.session-info`、`.user-message`、`.assistant-message` 等样式
   - 对话历史采用聊天气泡样式展示

## 使用方式

### Web UI（推荐）

1. 启动后端服务：
   ```bash
   uvicorn src.serve:app --reload
   ```

2. 打开 `index.html`

3. 开始对话：
   - 输入问题，点击"发送"
   - 继续追问，Agent 会记住上下文
   - 点击"新建会话"可清空历史

### CLI 交互模式

```bash
# 手写版多轮对话
python src/agent.py --chat

# Function Calling 版多轮对话
python src/agent.py --mode fc --chat
```

在交互模式中：
- 直接输入问题进行对话
- 输入 `/new` 清空历史
- 输入 `/history` 查看历史
- 输入 `exit` 或 `quit` 退出

## 技术细节

### 对话历史格式

对话历史采用 OpenAI API 的标准格式：
```python
[
    {"role": "user", "content": "问题1"},
    {"role": "assistant", "content": "回答1"},
    {"role": "user", "content": "追问2"},
    {"role": "assistant", "content": "回答2"},
]
```

### 会话存储

- 当前实现使用内存存储（`dict`），重启服务会丢失所有会话
- 生产环境建议：
  - 使用 Redis 等持久化存储
  - 增加会话过期清理机制
  - 考虑使用数据库存储长期历史

### 流式响应

- 使用 SSE（Server-Sent Events）实现流式输出
- 每个步骤实时推送到前端
- 最后推送 `done` 事件，包含最终答案
- 前端在收到 `done` 后保存对话到历史

## 兼容性

- **向后兼容**：保留了原有的 `/query/{mode}` 端点，单次查询仍然可用
- **前端兼容**：旧版前端（不使用多轮对话）仍可正常工作
- **评估脚本**：`evaluate.py` 不需要修改，它使用的是底层的 `run()` 函数

## 后续优化建议

1. **持久化存储**：将会话存储到 Redis 或数据库
2. **会话清理**：增加自动过期机制，避免内存泄漏
3. **历史长度限制**：限制对话历史长度，避免超出模型上下文窗口
4. **用户认证**：如果需要多用户支持，增加用户认证和会话归属
5. **流式保存**：当前是在流结束后保存历史，可考虑边流式边保存（需要更复杂的状态管理）
