"""
主 agent 下发子 agent 示例。


能力边界：
  1. 主 agent 和子 agent 使用同一份模型配置。
  2. 主 agent 可以调用 web_search、weather、delegate_to_subagent。
  3. 子 agent 只能调用 web_search、weather，不能继续下发任务。
  4. 大模型自行判断是否需要下发子 agent。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from openai import OpenAI

from tavily_search import format_search_result, tavily_search
from weather_backend import get_city_latAndlon, get_weather, get_weather_by_latlon


# ── 日志 ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ── 模型配置 ──────────────────────────────────────────────────────────────────

MODEL_CONFIG = {
    "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
    "base_url": "https://token.longshine.com/v1",
    "model": "kimi-k2.6",
}


@dataclass(frozen=True)
class AgentContext:
    """agent 的运行身份和权限。"""

    name: str
    role: str
    can_delegate: bool


ToolHandler = Callable[[dict[str, Any], AgentContext], str]


# ── 配置校验 ──────────────────────────────────────────────────────────────────


def validate_model_config(config: dict[str, str]) -> None:
    """运行前强制校验大模型必要配置。"""
    missing = [key for key in ("api_key", "base_url", "model") if not config.get(key)]
    if missing:
        tips = {
            "api_key": "export DEEPSEEK_API_KEY='你的 key'",
            "base_url": "确认 MODEL_CONFIG['base_url'] 已填写",
            "model": "确认 MODEL_CONFIG['model'] 已填写",
        }
        detail = "\n".join(f"  - {key}: {tips[key]}" for key in missing)
        raise RuntimeError(f"大模型配置缺失：{', '.join(missing)}\n请先设置：\n{detail}")


# ── 工具定义 ──────────────────────────────────────────────────────────────────


def tool_schema(can_delegate: bool) -> list[dict[str, Any]]:
    """按权限生成工具清单：子 agent 不拥有 delegate_to_subagent。"""
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "联网搜索实时信息，适合查询新闻、市场、政策、实时资料和需要来源的信息。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "max_results": {
                            "type": "integer",
                            "description": "返回结果数量，默认 5",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "weather",
                "description": "按城市查询天气，会自动完成城市经纬度查询和天气查询。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名，例如 北京、上海、宁德"}
                    },
                    "required": ["city"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_city_latAndlon",
                "description": "查询城市经纬度，返回 JSON 字符串，适合模型需要先定位城市时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名，例如 北京、上海、宁德"}
                    },
                    "required": ["city"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_weather_by_latlon",
                "description": "根据经纬度查询天气，通常接在 get_city_latAndlon 之后使用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "纬度"},
                        "lon": {"type": "number", "description": "经度"},
                        "city_name": {"type": "string", "description": "城市显示名，可选"},
                    },
                    "required": ["lat", "lon"],
                },
            },
        },
    ]

    # 这里是“是否允许下发子 agent”的第一道开关。
    # 主 agent 调用 tool_schema(True)：工具列表包含 delegate_to_subagent。
    # 子 agent 调用 tool_schema(False)：工具列表不包含 delegate_to_subagent。
    # 因此模型只能在主 agent 阶段看到“下发子 agent”的工具。
    if can_delegate:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "delegate_to_subagent",
                    "description": (
                        "把一个独立子任务下发给子 agent。适合资料搜集、天气查询、事实核验、"
                        "多步骤问题拆分。子 agent 不能继续下发任务。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": "交给子 agent 的明确任务，包含必要上下文和期望输出",
                            }
                        },
                        "required": ["task"],
                    },
                },
            }
        )

    return tools


# ── 系统提示词 ────────────────────────────────────────────────────────────────


def build_system_prompt(ctx: AgentContext) -> str:
    delegate_rule = (
        "你可以在任务适合拆分、需要并行调研或需要独立核验时调用 delegate_to_subagent 下发子任务。"
        if ctx.can_delegate
        else "你是子 agent，禁止下发任务；你没有 delegate_to_subagent 工具，只能自己完成当前任务。"
    )
    return f"""
你是{ctx.name}，当前身份是{ctx.role}。

可用能力：
- web_search：可以联网搜索，底层来自 tavily_search.py。
- weather：可以查询天气，底层来自 weather_backend.py。
- get_city_latAndlon：可以把城市转换为经纬度。
- get_weather_by_latlon：可以按经纬度查询天气。

任务分工规则：
- {delegate_rule}
- 如果用户问题能直接回答，直接回答。
- 如果问题需要实时资料，优先调用 web_search。
- 如果问题涉及天气，优先调用 weather；需要精细链路时再调用 get_city_latAndlon + get_weather_by_latlon。
- 回答要说明关键依据，不要编造工具没有返回的信息。
""".strip()


# ── 工具执行 ──────────────────────────────────────────────────────────────────


def safe_json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("工具参数不是合法 JSON：%s", raw)
        return {}


def handle_web_search(args: dict[str, Any], ctx: AgentContext) -> str:
    query = str(args.get("query", "")).strip()
    max_results = int(args.get("max_results") or 5)
    logger.info("[%s] 调用工具 web_search | query=%s", ctx.name, query)
    if not query:
        return "web_search 缺少 query 参数"
    return format_search_result(tavily_search(query=query, max_results=max_results))


def handle_weather(args: dict[str, Any], ctx: AgentContext) -> str:
    city = str(args.get("city", "")).strip()
    logger.info("[%s] 调用工具 weather | city=%s", ctx.name, city)
    if not city:
        return "weather 缺少 city 参数"
    return get_weather(city)


def handle_city_latlon(args: dict[str, Any], ctx: AgentContext) -> str:
    city = str(args.get("city", "")).strip()
    logger.info("[%s] 调用工具 get_city_latAndlon | city=%s", ctx.name, city)
    if not city:
        return "get_city_latAndlon 缺少 city 参数"
    return get_city_latAndlon(city)


def handle_weather_by_latlon(args: dict[str, Any], ctx: AgentContext) -> str:
    logger.info("[%s] 调用工具 get_weather_by_latlon | args=%s", ctx.name, args)
    try:
        lat = float(args["lat"])
        lon = float(args["lon"])
    except (KeyError, TypeError, ValueError):
        return "get_weather_by_latlon 缺少合法的 lat/lon 参数"
    return get_weather_by_latlon(lat=lat, lon=lon, city_name=str(args.get("city_name", "")))


def build_tool_handlers(client: OpenAI) -> dict[str, ToolHandler]:
    # delegate_to_subagent 是“主 agent 下发子 agent”的入口函数。
    # 当大模型决定调用这个工具时，代码才会真正创建并运行子 agent。
    def handle_delegate(args: dict[str, Any], ctx: AgentContext) -> str:
        # 权限兜底：即使模型误请求下发，子 agent 也会在这里被拦截。
        if not ctx.can_delegate:
            logger.warning("[%s] 拒绝下发：子 agent 无下发权限", ctx.name)
            return "当前 agent 没有下发子 agent 的权限"

        # 这里开始进入“主 agent 下发子 agent”的流程：
        # task 是主 agent 交给子 agent 的独立任务说明。
        task = str(args.get("task", "")).strip()
        logger.info("[%s] 下发子 agent | task=%s", ctx.name, task)
        if not task:
            return "delegate_to_subagent 缺少 task 参数"

        sub_ctx = AgentContext(name="SubAgent", role="子 agent", can_delegate=False)
        logger.info("[MainAgent] 子 agent 状态=执行中 | task=%s", task)
        result = run_agent(
            client=client,
            ctx=sub_ctx,
            user_input=task,
            max_rounds=8,
        )
        logger.info("[MainAgent] 子 agent 状态=已完成")
        logger.info("[%s] 子 agent 返回结果", ctx.name)
        return result

    return {
        "web_search": handle_web_search,
        "weather": handle_weather,
        "get_city_latAndlon": handle_city_latlon,
        "get_weather_by_latlon": handle_weather_by_latlon,
        "delegate_to_subagent": handle_delegate,
    }


# ── Agent 循环 ────────────────────────────────────────────────────────────────


def run_agent(client: OpenAI, ctx: AgentContext, user_input: str, max_rounds: int = 10) -> str:
    logger.info("[%s] 开始执行 | can_delegate=%s", ctx.name, ctx.can_delegate)
    if not ctx.can_delegate:
        logger.info("[SubAgent] 子 agent 状态=执行中 | 已进入子 agent 执行循环")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(ctx)},
        {"role": "user", "content": user_input},
    ]
    handlers = build_tool_handlers(client)

    for round_index in range(1, max_rounds + 1):
        logger.info("[%s] 请求模型 | round=%s", ctx.name, round_index)
        response = client.chat.completions.create(
            model=MODEL_CONFIG["model"],
            messages=messages,
            tools=tool_schema(can_delegate=ctx.can_delegate),
            tool_choice="auto",
        )
        message = response.choices[0].message
        messages.append(message.model_dump())

        if not message.tool_calls:
            answer = message.content or ""
            if ctx.can_delegate:
                logger.info("[MainAgent] 子 agent 状态=未执行 | 本轮由主 agent 直接回答")
            else:
                logger.info("[SubAgent] 子 agent 状态=执行完成 | 本轮由子 agent 生成回答")
            logger.info("[%s] 执行完成", ctx.name)
            return answer

        logger.info("[%s] 模型决定调用 %s 个工具", ctx.name, len(message.tool_calls))
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            args = safe_json_loads(tool_call.function.arguments)
            handler = handlers.get(name)
            if handler is None:
                result = f"未知工具：{name}"
                logger.warning("[%s] %s", ctx.name, result)
            else:
                result = handler(args, ctx)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": name,
                    "content": result,
                }
            )

    logger.warning("[%s] 达到最大轮次，提前结束", ctx.name)
    return "任务未在最大轮次内完成，请缩小问题范围后重试。"


# ── CLI 入口 ─────────────────────────────────────────────────────────────────


def main() -> None:
    validate_model_config(MODEL_CONFIG)
    client = OpenAI(
        api_key=MODEL_CONFIG["api_key"],
        base_url=MODEL_CONFIG["base_url"],
    )

    logger.info("模型配置检查通过 | base_url=%s | model=%s", MODEL_CONFIG["base_url"], MODEL_CONFIG["model"])
    logger.info("输入 exit / quit 结束程序")

    main_ctx = AgentContext(name="MainAgent", role="主 agent", can_delegate=True)
    while True:
        user_input = input("\n用户输入 > ").strip()
        if user_input.lower() in {"exit", "quit"}:
            logger.info("程序退出")
            break
        if not user_input:
            continue

        answer = run_agent(client=client, ctx=main_ctx, user_input=user_input)
        print("\n最终回答：")
        print(answer)


if __name__ == "__main__":
    main()