# USAGE_GUIDE.md — 多轮对话 + 工具调用

## 1. 依赖

```bash
pip install openai faiss-cpu akshare fastapi uvicorn numpy
```

环境变量：

```bash
export DASHSCOPE_API_KEY="sk-xxx"
export AGENT_MODEL="qwen-max"
```

---

## 2. CLI

进入目录：

```bash
cd react_financial_agent/src
```

单轮执行：

```bash
python agent.py --question "茅台和五粮液2023年毛利率差多少？"
```

交互式多轮对话：

```bash
python agent.py --chat
```

支持命令：

- `/reset`：重置会话
- `/exit`：退出

---

## 3. Web 服务

启动：

```bash
cd react_financial_agent/src
uvicorn serve:app --host 0.0.0.0 --port 8000
```

打开 `http://localhost:8000`。

接口：

- `POST /query`：发送问题，支持 `session_id` 维持多轮对话
- `POST /reset`：重置会话
- `GET /health`：健康检查

---

## 4. 多轮对话工作方式

同一个 `messages` 列表会在多轮之间复用，保留：

- system prompt
- 之前的 user 提问
- agent 的中间工具调用轨迹
- 之前的 final answer

这样后续问题可以直接引用上文，例如：

1. `茅台和五粮液2023年毛利率差多少？`
2. `那差多少个百分点？`
3. `再把这个差值换算成元给我看`

---

## 5. 代码调用

```python
import sys
sys.path.insert(0, "react_financial_agent/src")

from react_manual import ConversationSession

session = ConversationSession()
for step in session.ask("茅台和五粮液2023年毛利率差多少？"):
    print(step)

for step in session.ask("那差多少个百分点？"):
    print(step)
```

---

## 6. 已移除内容

旧的双实现、对比评估和双路由入口已经移除，当前只保留带工具调用的单一主流程。
