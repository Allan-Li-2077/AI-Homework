# 并行 Subagent Agent

这是一个最小可运行的 Python 实现：主 agent 会把多个任务分发给不同的子 agent，并行执行后汇总结果。

## 功能

- 接收一组任务。
- 按 `kind` 把任务路由到匹配的 `SubAgent`。
- 使用 `asyncio` 的信号量并发执行任务。
- 将子 agent 的失败隔离到 `TaskResult` 中，不影响其他任务。
- 支持输出 Markdown 报告或 JSON。

## 运行

```powershell
python -m work.subagent_agent.core
```

也可以直接双击项目根目录下的 `run.bat`。

使用自定义任务文件：

```powershell
python -m work.subagent_agent.core --tasks work/subagent_agent/tasks.example.json
```

输出 JSON：

```powershell
python -m work.subagent_agent.core --json
```

限制并发数：

```powershell
python -m work.subagent_agent.core --max-parallel 2
```

## 任务格式

```json
{
  "title": "Implement feature",
  "kind": "code",
  "description": "Make the smallest useful version of the requested system."
}
```

## 扩展方式

新增一个 worker 函数：

```python
async def test_worker(task: Task) -> str:
    return f"Tests created for {task.title}"
```

注册它：

```python
SubAgent("test-agent", ["test"], test_worker)
```

在生产环境里，每个 worker 可以调用真实的 LLM、工具服务、任务队列
或者另一个进程，而不是返回示例文本。
