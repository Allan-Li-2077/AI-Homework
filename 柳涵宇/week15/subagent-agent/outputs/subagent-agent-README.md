# Parallel Subagent Agent

Implemented in `work/subagent_agent`.

Run:

```powershell
python -m work.subagent_agent.core
```

Run with custom tasks:

```powershell
python -m work.subagent_agent.core --tasks work/subagent_agent/tasks.example.json
```

Key capabilities:

- Main agent routes work to specialized subagents.
- Subagents run concurrently.
- `--max-parallel` controls concurrency.
- Failures are captured per task instead of crashing the whole run.
- `--json` returns machine-readable results.
