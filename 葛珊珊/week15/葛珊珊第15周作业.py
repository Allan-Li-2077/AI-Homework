── 主 agent 第 1 轮推理 ──

🚀 并行下发 3 个 subagent: 目标客群画像与定位分析, 菜单设计（招牌饮品3款+烘焙搭配）, 开业首周社媒推广方案（小红书+抖音）
  ↳ 派发 subagent [目标客群画像与定位分析] ...
  ↳ 派发 subagent [菜单设计（招牌饮品3款+烘焙搭配）] ...
  ↳ 派发 subagent [开业首周社媒推广方案（小红书+抖音）] ...
✅ 全部 subagent 完成，耗时 58.15s

── 主 agent 第 2 轮推理 ──

📝 主 agent 输出最终答案（第 2 轮）

============================================================
📊 执行统计
   主 agent 推理轮数 : 2
   下发次数          : 1
   subagent 总数     : 3
   总耗时            : 94.06s
============================================================

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
最终答案：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三个方向的独立分析已完成，以下是我综合三份结果后为你整合的完整开业策划方案，最后附上可落地的开业执行清单。

---

# 精品咖啡店开业策划方案

## 一、目标客群画像与定位

### 1. 四类核心客群画像

| 维度 | A 资深咖啡爱好者 | B 都市白领/商务 | C 自由职业者/远程办公 | D 社交打卡人群 |
|---|---|---|---|---|
| 年龄 | 25-40岁 | 25-38岁 | 22-35岁 | 20-32岁 |
| 消费频次 | 每周4次+ | 工作日每日1次 | 每周3-5次 | 每月1-3次 |
| 到店场景 | 品鉴新品、买豆、与咖啡师交流 | 早高峰外带、下午提神、商务会面 | 带电脑长坐办公学习 | 周末下午茶、拍照打卡 |
| 价格敏感度 | 低（为品质买单） | 中（要效率与性价比） | 中高（要"划算地待一天"） | 中（为情绪价值付费） |








"""
parallel_agent.py
=================
一个可以自主下发 subagent 并行完成多项工作的 agent 框架。

架构：
    ┌───────────────────────────────────────────┐
    │           ParallelOrchestrator            │  ← 主 agent
    │  (LLM + function calling 自主决策何时拆分) │
    └──────────────────┬────────────────────────┘
                       │ dispatch_subagents(tasks)
        ┌──────────────┼──────────────┐  (asyncio.gather 并行)
        ▼              ▼              ▼
   ┌─────────┐    ┌─────────┐    ┌─────────┐
   │SubAgent │    │SubAgent │    │SubAgent │   ← 纯 LLM 推理
   │ task A  │    │ task B  │    │ task C  │
   └────┬────┘    └────┬────┘    └────┬────┘
        └──────────────┼──────────────┘
                       ▼
              主 agent 汇总结果 → 最终答案

主 agent 通过 function calling 自主判断：
  - 任务简单 → 直接回答
  - 任务可拆分 → 调用 dispatch_subagents 工具并行下发
  - 收到子结果后继续推理，可多次下发，直到给出最终答案

默认接入 DeepSeek（OpenAI 兼容协议），通过 httpx 直接调用。
依赖极简：仅需 httpx（纯 Python，不含 pydantic 原生扩展，避开 DLL 拦截问题）。

环境变量 / .env：
  DEEPSEEK_API_KEY  : DeepSeek API 密钥（必填）
  AGENT_MODEL       : 主 agent 模型，默认 deepseek-v4-flash
  AGENT_SUB_MODEL   : subagent 模型，默认同 AGENT_MODEL
  DEEPSEEK_BASE_URL : 可选，默认 https://api.deepseek.com
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


# ─────────────────────────────────────────────────────────────────────────────
# .env 加载（无第三方依赖）
# ─────────────────────────────────────────────────────────────────────────────

def _load_dotenv() -> None:
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Config:
    """从环境变量读取，默认接入 DeepSeek。"""
    base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("AGENT_MODEL", "deepseek-v4-flash"))
    sub_model: str = field(default_factory=lambda: os.getenv("AGENT_SUB_MODEL", os.getenv("AGENT_MODEL", "deepseek-v4-flash")))
    max_iters: int = field(default_factory=lambda: int(os.getenv("MAX_ITERS", "6")))
    max_concurrency: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENCY", "8")))
    timeout: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT", "120")))


# ─────────────────────────────────────────────────────────────────────────────
# 极简 OpenAI 兼容客户端（纯 httpx，零原生依赖）
# ─────────────────────────────────────────────────────────────────────────────

class ChatMessage:
    def __init__(self, role: str, content: str | None = None,
                 tool_calls: list[dict] | None = None,
                 tool_call_id: str | None = None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.tool_call_id = tool_call_id

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls is not None:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        return d


class _ToolCallObj:
    def __init__(self, raw: dict):
        self.id: str = raw.get("id", "")
        func = raw.get("function", {}) or {}
        self.function = type("F", (), {})()
        self.function.name = func.get("name", "")
        args = func.get("arguments", "")
        if isinstance(args, dict):
            self.function.arguments = json.dumps(args, ensure_ascii=False)
        else:
            self.function.arguments = args or "{}"


class _MessageObj:
    def __init__(self, raw: dict):
        self.content: str | None = raw.get("content")
        self.tool_calls: list[_ToolCallObj] | None = None
        if raw.get("tool_calls"):
            self.tool_calls = [_ToolCallObj(tc) for tc in raw["tool_calls"]]


class _ChoiceObj:
    def __init__(self, raw: dict):
        self.message = _MessageObj(raw.get("message", {}))


class ChatResponse:
    def __init__(self, raw: dict):
        self.raw = raw
        self.choices = [_ChoiceObj(c) for c in raw.get("choices", [])]


class LLMClient:
    """极简 OpenAI 兼容 async 客户端。"""

    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat(self, *, model: str, messages: list[ChatMessage],
                   tools: list[dict] | None = None,
                   tool_choice: str | None = "auto",
                   temperature: float = 0.2) -> ChatResponse:
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
        }
        if tools is not None:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        resp = await client.post("/chat/completions", json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"LLM 调用失败 [{resp.status_code}] {resp.text[:500]}"
            )
        return ChatResponse(resp.json())


# ─────────────────────────────────────────────────────────────────────────────
# SubAgent
# ─────────────────────────────────────────────────────────────────────────────

class SubAgent:
    def __init__(self, name: str, description: str, client: LLMClient, model: str):
        self.name = name
        self.description = description
        self.client = client
        self.model = model

    async def run(self) -> dict[str, Any]:
        system = (
            "你是一个专注、高效的 subagent。你会收到一个明确的子任务，"
            "请直接给出高质量的分析结果，不要寒暄、不要重复任务描述。"
            "如果任务要求结构化输出，请用清晰的格式（如 markdown / json）作答。"
        )
        start = time.time()
        try:
            resp = await self.client.chat(
                model=self.model,
                messages=[
                    ChatMessage("system", system),
                    ChatMessage("user",
                                f"【子任务名称】{self.name}\n【子任务描述】{self.description}\n\n请完成该子任务。"),
                ],
                temperature=0.3,
            )
            result = resp.choices[0].message.content or ""
            return {
                "name": self.name,
                "description": self.description,
                "success": True,
                "result": result.strip(),
                "elapsed": round(time.time() - start, 2),
            }
        except Exception as e:  # noqa: BLE001
            return {
                "name": self.name,
                "description": self.description,
                "success": False,
                "result": f"[subagent 执行失败] {type(e).__name__}: {e}",
                "elapsed": round(time.time() - start, 2),
            }

    def __repr__(self) -> str:
        return f"<SubAgent {self.name}>"


# ─────────────────────────────────────────────────────────────────────────────
# 主 agent
# ─────────────────────────────────────────────────────────────────────────────

DISPATCH_TOOL = {
    "type": "function",
    "function": {
        "name": "dispatch_subagents",
        "description": (
            "将一个复杂任务拆解为多个相互独立的子任务，并行下发给 subagent 执行。"
            "仅当子任务之间确实可以并行、且拆分能带来收益时才调用。"
            "简单的任务请直接回答，不要调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "需要并行执行的子任务列表，每个子任务应独立、明确、可并行",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "子任务的简短名称"},
                            "description": {
                                "type": "string",
                                "description": "子任务的详细描述，包含背景、要求、输出格式等",
                            },
                        },
                        "required": ["name", "description"],
                    },
                }
            },
            "required": ["tasks"],
        },
    },
}

ORCHESTRATOR_SYSTEM = """你是一个善于任务编排的主 agent（orchestrator）。

你的工作流程：
1. 分析用户请求的复杂度。
2. 如果任务可以拆成多个相互独立的子任务并行处理，调用 `dispatch_subagents` 工具下发；
   拆分时确保每个子任务边界清晰、可独立完成，避免子任务之间存在依赖。
3. 收到各 subagent 返回的结果后，综合它们的输出给出最终答案。
4. 如果一次拆分不足以完成任务，可以多次调用 `dispatch_subagents`。
5. 任务简单时直接回答，不要为了用工具而用工具。

最终答案要求：
- 综合所有 subagent 的结果，不要简单堆砌，要做整合与提炼。
- 用清晰的结构（标题、分点、表格等）呈现。
- 如有 subagent 失败，指出缺失部分并尽量用其它结果补救。
"""


class ParallelOrchestrator:
    """主 agent：通过 function calling 自主决定何时下发 subagent 并行执行。"""

    def __init__(self, config: Config | None = None, client: LLMClient | None = None):
        self.config = config or Config()
        if client is not None:
            self.client = client
        else:
            if not self.config.api_key:
                raise ValueError(
                    "未检测到 DEEPSEEK_API_KEY。\n"
                    "  1) PowerShell: $env:DEEPSEEK_API_KEY = \"sk-xxx\"\n"
                    "  2) cmd.exe:    set DEEPSEEK_API_KEY=sk-xxx\n"
                    "  3) bash/zsh:   export DEEPSEEK_API_KEY=sk-xxx\n"
                    "  4) 或在项目根目录创建 .env 文件，写 DEEPSEEK_API_KEY=sk-xxx"
                )
            self.client = LLMClient(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                timeout=self.config.timeout,
            )
        self.stats = {"dispatch_count": 0, "subagent_count": 0, "iters": 0}

    async def dispatch_subagents(self, tasks: list[dict[str, str]]) -> list[dict[str, Any]]:
        sem = asyncio.Semaphore(self.config.max_concurrency)

        async def _run(task: dict[str, str]) -> dict[str, Any]:
            async with sem:
                agent = SubAgent(
                    name=task["name"],
                    description=task["description"],
                    client=self.client,
                    model=self.config.sub_model,
                )
                print(f"  ↳ 派发 subagent [{agent.name}] ...")
                return await agent.run()

        names = ", ".join(t["name"] for t in tasks)
        print(f"\n🚀 并行下发 {len(tasks)} 个 subagent: {names}")
        start = time.time()
        results = await asyncio.gather(*[_run(t) for t in tasks])
        print(f"✅ 全部 subagent 完成，耗时 {time.time() - start:.2f}s\n")
        self.stats["dispatch_count"] += 1
        self.stats["subagent_count"] += len(tasks)
        return list(results)

    async def run(self, user_request: str) -> str:
        messages = [
            ChatMessage("system", ORCHESTRATOR_SYSTEM),
            ChatMessage("user", user_request),
        ]

        for i in range(1, self.config.max_iters + 1):
            self.stats["iters"] = i
            print(f"── 主 agent 第 {i} 轮推理 ──")
            resp = await self.client.chat(
                model=self.config.model,
                messages=messages,
                tools=[DISPATCH_TOOL],
                tool_choice="auto",
                temperature=0.2,
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
                final = msg.content or "(主 agent 未返回内容)"
                print(f"\n📝 主 agent 输出最终答案（第 {i} 轮）\n")
                return final

            # 回填 assistant 消息（含 tool_calls 字段）
            tc_dicts = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
            messages.append(ChatMessage(
                role="assistant",
                content=msg.content,
                tool_calls=tc_dicts,
            ))

            for call in msg.tool_calls:
                if call.function.name == "dispatch_subagents":
                    args = json.loads(call.function.arguments or "{}")
                    tasks = args.get("tasks", [])
                    if not tasks:
                        messages.append(ChatMessage("tool", "未提供任何子任务。", tool_call_id=call.id))
                        continue
                    results = await self.dispatch_subagents(tasks)
                    messages.append(ChatMessage(
                        role="tool",
                        content=json.dumps(results, ensure_ascii=False, indent=2),
                        tool_call_id=call.id,
                    ))
                else:
                    messages.append(ChatMessage("tool", f"未知工具: {call.function.name}", tool_call_id=call.id))

        return "⚠️ 已达到最大推理轮数，未得到最终答案。"

    async def run_and_report(self, user_request: str) -> str:
        start = time.time()
        answer = await self.run(user_request)
        elapsed = time.time() - start
        print("=" * 60)
        print("📊 执行统计")
        print(f"   主 agent 推理轮数 : {self.stats['iters']}")
        print(f"   下发次数          : {self.stats['dispatch_count']}")
        print(f"   subagent 总数     : {self.stats['subagent_count']}")
        print(f"   总耗时            : {elapsed:.2f}s")
        print("=" * 60)
        return answer


# ─────────────────────────────────────────────────────────────────────────────
# 示例入口
# ─────────────────────────────────────────────────────────────────────────────

EXAMPLE_REQUEST = (
    "我想为一家新开的精品咖啡店做开业策划，请帮我同时分析以下三个方面并给出建议：\n"
    "1. 目标客群画像与定位\n"
    "2. 菜单设计（含招牌饮品 3 款 + 烘焙搭配）\n"
    "3. 开业首周的社交媒体推广方案（小红书 + 抖音）\n"
    "最后请综合三方面给出一份开业执行清单。"
)


async def main():
    agent = ParallelOrchestrator()
    try:
        answer = await agent.run_and_report(EXAMPLE_REQUEST)
    finally:
        await agent.client.aclose()
    print("\n" + "━" * 60)
    print("最终答案：")
    print("━" * 60)
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())















