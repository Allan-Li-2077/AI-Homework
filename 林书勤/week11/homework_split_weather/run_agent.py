"""
run_agent.py — Function Calling Agent Loop 实现

核心概念：
  Agent Loop 是一个循环执行框架，让 LLM 能够：
  1. 自主决定何时调用工具
  2. 根据工具返回结果进行推理
  3. 链式调用多个工具完成复杂任务
  4. 判断何时给出最终答案

与单轮 Function Calling 的对比：
  单轮模式：
    User Question → LLM → Tool Call → Tool Result → LLM → Final Answer
    (固定两次 LLM 调用)
  
  Agent Loop：
    User Question → [LLM → Tool Call → Tool Result] × N → LLM → Final Answer
    (循环直到 LLM 决定停止)

实现的三种调用模式：
  1. 链式调用：geocode("宁德") → get_weather_by_coords(26.66, 119.52)
  2. 单工具 A：geocode("北京") → 直接返回经纬度
  3. 单工具 B：get_weather_by_coords(39.9, 116.4) → 直接返回天气

技术栈：
  - OpenAI SDK：统一接口调用多家 LLM
  - DeepSeek/DashScope：支持 Function Calling 的模型提供商
  
使用示例：
  python run_agent.py -q "宁德今天的天气怎么样？"
  python run_agent.py --demo
  python run_agent.py --provider dashscope -q "北京的经纬度"
"""

import json
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

# 让 weather_tools 可被 import（直接 python 运行本脚本也能找到）
sys.path.insert(0, str(Path(__file__).parent))

from weather_tools import geocode, get_weather_by_coords  # noqa: E402

# ── LLM 配置（参考 mode_function_call/run_function_call.py）─────────────────

PROVIDERS = {
    "deepseek": {
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "dashscope": {
        "api_key": os.environ.get("DASHSCOPE_API_KEY", ""),
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
}


def build_client(provider: str):
    cfg = PROVIDERS[provider]
    if not cfg["api_key"]:
        print(f"错误：未设置 {provider.upper()}_API_KEY", file=sys.stderr)
        sys.exit(1)
    return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"]), cfg["model"]


# ── 工具 Schema：两个拆分后的工具 ───────────────────────────────────────────

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "geocode",
            "description": (
                "把城市名解析成经纬度（地理编码）。输入中文城市名如'北京'、'宁德'，"
                "返回该城市的纬度 latitude 和经度 longitude。"
                "当用户问'某城市的经纬度/坐标'时直接用本工具即可；"
                "当用户问'某城市天气'但本工具不含天气查询时，先用本工具拿到经纬度，"
                "再把经纬度传给 get_weather_by_coords 查天气（链式调用）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市中文名，如 '宁德'、'北京'"},
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_by_coords",
            "description": (
                "按经纬度查询当前天气及未来3天预报。参数是数值型的纬度/经度。"
                "若用户已直接给出经纬度，直接调用本工具；"
                "若用户只给了城市名，请先调用 geocode 拿到经纬度，再调用本工具（链式）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {"type": "number", "description": "纬度，如 39.9"},
                    "longitude": {"type": "number", "description": "经度，如 116.4"},
                },
                "required": ["latitude", "longitude"],
            },
        },
    },
]

# 工具名 → 后端函数 的派发表（业务逻辑与协议层分离）
TOOL_DISPATCH = {
    "geocode": geocode,
    "get_weather_by_coords": get_weather_by_coords,
}

SYSTEM_PROMPT = (
    "你是一名智能天气助手，拥有两个专业工具：\n\n"
    "1. geocode: 将城市名转换为地理坐标\n"
    "2. get_weather_by_coords: 根据坐标查询天气\n\n"
    "工作流程：\n"
    "- 若用户询问城市天气，先调用 geocode 获取坐标，再调用 get_weather_by_coords 查询\n"
    "- 若用户仅询问经纬度，只需调用 geocode\n"
    "- 若用户已提供坐标，直接调用 get_weather_by_coords\n\n"
    "原则：\n"
    "- 严格依据工具返回的真实数据回答\n"
    "- 不编造、不猜测、不使用过时信息\n"
    "- 遇到不确定情况，明确说明原因"
)

def run(client, model: str, question: str, verbose: bool = True) -> dict:
    """
    Agent Loop 核心执行函数
    
    流程：
      1. 初始化对话上下文（system + user）
      2. 循环调用 LLM：
         a. LLM 返回工具调用 → 执行工具 → 回填结果 → 继续循环
         b. LLM 不调用工具 → 返回最终答案 → 结束
      3. 防御性兜底：最多循环 MAX_STEPS 次
    
    参数：
      client: OpenAI 客户端实例
      model: 模型名称（如 deepseek-chat）
      question: 用户问题
      verbose: 是否打印中间步骤
    
    返回：
      {
        "answer": 最终回答文本,
        "tool_calls": 工具调用记录列表,
        "steps": 实际循环轮数,
        "elapsed": 总耗时（秒）
      }
    
    设计要点：
      - 每轮循环都将 assistant 消息和 tool 结果完整回填
      - 由 LLM 自主决定何时终止（finish_reason == "stop"）
      - 支持链式调用：一轮内可调用多个工具
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    t0 = time.time()
    tool_call_log = []

    for step in range(1, MAX_STEPS + 1):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        # 模型本轮不再调用工具 → 已经是最终回答，退出循环
        if not msg.tool_calls:
            if verbose:
                print(f"  → [llm] 最终回答（第{step}轮，共{time.time() - t0:.1f}s）")
            return {
                "answer": msg.content or "",
                "tool_calls": tool_call_log,
                "steps": step,
                "elapsed": time.time() - t0,
            }

        # 把 assistant 这条带 tool_calls 的消息原样回填，保持上下文
        messages.append(msg)

        # 逐个执行模型本轮要调的工具
        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            tool_call_log.append({"name": name, "args": args})
            if verbose:
                print(f"  → [tool step {step}] {name}({args})")
            fn = TOOL_DISPATCH.get(name)
            if fn is None:
                result = f"未知工具：{name}"
            else:
                try:
                    result = fn(**args)
                except TypeError as e:
                    result = f"参数错误：{e}"
                except Exception as e:
                    result = f"工具执行失败：{e}"
            preview = (result or "")[:120].replace("\n", " ")
            if verbose:
                print(f"    ↩ {preview}{'...' if len(result or '') > 120 else ''}\n")
            # 以 role=tool 回填，tool_call_id 必须对上
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
        # 循环回到顶部，让模型看到工具结果后决定：继续调工具 or 给最终回答

    return {
        "answer": "（达到最大步数，模型仍未给出最终回答）",
        "tool_calls": tool_call_log,
        "steps": MAX_STEPS,
        "elapsed": time.time() - t0,
    }


# ── 入口 ───────────────────────────────────────────────────────────────────

DEMO_QUESTIONS = [
    "宁德今天的天气怎么样？",              # 链式：geocode → get_weather_by_coords
    "北京的经纬度是多少？",              # 单工具：只 geocode
    "经度116.4、纬度39.9 这个地方天气如何？",  # 单工具：只 get_weather_by_coords
]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="作业：拆分天气工具 + agent loop")
    parser.add_argument("--question", "-q", help="单个问题")
    parser.add_argument("--demo", action="store_true", help="跑内置示例问题集")
    parser.add_argument("--provider", default="deepseek", choices=PROVIDERS.keys())
    parser.add_argument("--quiet", action="store_true", help="少输出")
    args = parser.parse_args()

    client, model = build_client(args.provider)
    print(f"[Split Weather Agent] provider={args.provider} model={model}\n")

    questions = DEMO_QUESTIONS if args.demo else ([args.question] if args.question else [DEMO_QUESTIONS[0]])
    for i, q in enumerate(questions, 1):
        print("=" * 60)
        print(f"Q{i}：{q}")
        print("=" * 60)
        result = run(client, model, q, verbose=not args.quiet)
        print("\n最终回答：")
        print(result["answer"])
        print(f"\n（工具调用 {len(result['tool_calls'])} 次，循环 {result['steps']} 轮，"
              f"耗时 {result['elapsed']:.1f}s）\n")


if __name__ == "__main__":
    main()
