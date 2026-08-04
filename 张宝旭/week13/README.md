# Week 13: Progressive Skill Loading Harness

这个目录是一份可单独提交的作业包，主题是：**实现一个可以渐进式加载并执行 skills 的 harness**。

它从 mini-pi 项目里的 skill 体系抽出核心思路，但不包含主项目配置、模型配置、API Key、`.env`、`.mini-pi` 工作区状态或用户数据。`example_skills` 里的 `skill.json` 是示例 skill 的 manifest，属于测试素材，不是运行环境配置。

## 目标

传统做法会把所有 `SKILL.md` 一次性塞进 system prompt，问题是：

- prompt 迅速膨胀，模型上下文浪费明显。
- 未相关 skill 的长说明会干扰当前任务。
- 动态安装 skill 后，工具是否可用、何时暴露、如何执行缺少统一入口。

这个 harness 的策略是：

1. **Discovery**：启动时只扫描 manifest，得到 skill 摘要、触发词、能力和 runtime 声明。
2. **Catalog Context**：基础 prompt 里只放短摘要，告诉模型有哪些可用能力。
3. **Match**：每个用户请求到来后，根据 trigger 和 capability 判断本轮需要哪些 skill。
4. **Progressive Load**：只读取命中的 `SKILL.md`，把完整说明注入本轮任务上下文。
5. **Tool Exposure**：只把命中 skill 声明的 runtime tool 暴露给模型。
6. **Execution**：模型调用工具时，harness 根据 runtime runner 执行对应脚本或命令。

## 目录结构

```text
week13/
  README.md
  demo.py
  skill_harness/
    registry.py      # skill discovery / manifest loading / prompt matching
    runtime.py       # runtime tool schema generation and execution bridge
    harness.py       # orchestrates catalog -> match -> load -> expose -> execute
  example_skills/
    flash-card/
      SKILL.md
      skill.json
      scripts/make_flashcard.py
    timeline/
      SKILL.md
      skill.json
      scripts/make_timeline.py
  tests/
    test_progressive_harness.py
```

## 和 mini-pi 主项目的对应关系

- `mini_pi_core/skills/registry.py`：对应这里的 `skill_harness/registry.py`，负责扫描 skill、读取 manifest、匹配 prompt。
- `mini_pi_core/skills/runtime_v2.py` 和 `runtime_tools_v2.py`：对应这里的 `skill_harness/runtime.py`，负责把 runtime 声明转换成工具 schema，并执行动态工具。
- `mini_pi_core/runtime/agent_session.py` 里的 `prepare_task_skills`：对应这里的 `skill_harness/harness.py`，负责在每轮任务开始时执行渐进式加载。

## 快速运行

在项目根目录执行：

```bash
python week13/demo.py "帮我做一张 transformer 的学习卡片"
```

你会看到四段输出：

- `Progressive Events`：本轮发现、匹配、加载、暴露工具的事件。
- `Catalog Context`：基础上下文，只包含 skill 摘要。
- `Task Skill Context`：命中后才加载的完整 `SKILL.md`。
- `Tool Schemas`：只有命中 skill 的工具会暴露出来。

运行测试：

```bash
python -m pytest week13
```

## 新增一个本地 skill

新建目录：

```text
week13/example_skills/my-skill/
  SKILL.md
  skill.json
```

最小 manifest：

```json
{
  "id": "my-skill",
  "name": "My Skill",
  "description": "Short summary shown in catalog context.",
  "enabled": true,
  "triggers": ["my trigger"],
  "capabilities": ["my.capability"],
  "runtimeV2": {
    "capabilities": ["my.capability"],
    "tools": []
  }
}
```

如果要让 skill 执行脚本，在 `runtimeV2.tools` 里声明 runner：

```json
{
  "name": "my_tool",
  "capability": "my.capability",
  "description": "Run my local script.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "topic": { "type": "string" }
    },
    "required": ["topic"],
    "additionalProperties": false
  },
  "runner": {
    "type": "python",
    "script": "scripts/my_tool.py",
    "args": ["--topic", "{{topic}}"],
    "timeoutSeconds": 10
  }
}
```

## 关键设计点

**为什么叫 progressive loading？**

因为它不是“安装了多少 skill 就加载多少 skill”，而是分阶段加载：

| 阶段 | 读取内容 | 放进模型上下文 | 目的 |
| --- | --- | --- | --- |
| Discovery | `skill.json` | 短摘要 | 让 agent 知道有哪些能力 |
| Match | manifest triggers/capabilities | 不新增长文本 | 判断本轮要用谁 |
| Load | 命中的 `SKILL.md` | 完整说明 | 只注入相关 skill |
| Expose | 命中 skill 的 runtime tools | tool schema | 降低误调用概率 |
| Execute | runner 脚本或命令 | tool result | 把 skill 变成真实能力 |

**为什么不在源码里为每个 skill 写 if/else？**

因为 skill 的变化应该发生在 manifest 和 `SKILL.md` 里。harness 只理解统一协议：`id`、`triggers`、`capabilities`、`runtimeV2.tools`、`runner`。新增 skill 时，只要遵守协议，就不需要改 harness 源码。

**为什么需要 runtime tool？**

只把 skill 说明交给模型，模型仍然只能“说”。runtime tool 是技能真正可执行的部分，例如调用搜索 CLI、生成 Word、运行脚本、访问 MCP 或 HTTP API。这个作业版本为了可本地运行，只实现了安全的 `python` 和 `command` runner。

## 测试覆盖

当前测试覆盖三件事：

- catalog 阶段不会读取完整 `SKILL.md`。
- 一个 prompt 只会加载命中的 skill，不会加载无关 skill。
- 命中 skill 后才暴露 runtime tool，并且可以执行示例工具。
