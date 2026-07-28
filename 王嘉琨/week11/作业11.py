import json
from typing import List, Dict, Any

# ====================== 1. 模拟天气查询工具 ======================
def get_weather(city: str) -> str:
    """
    获取指定城市天气
    :param city: 城市名称
    """
    # 模拟接口请求
    mock_data = {
        "杭州": "晴，28~35℃，东南风3级",
        "宁波": "多云，27~33℃，微风",
        "上海": "小雨，25~30℃"
    }
    return f"{city}天气：{mock_data.get(city, '暂无该城市天气数据')}"

# 工具映射表：名称映射函数
tool_functions = {
    "get_weather": get_weather
}

# 工具定义（传给大模型的function schema）
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市当前天气情况",
            "parameters": {
                "type": "object",
                "required": ["city"],
                "properties": {
                    "city": {"type": "string", "description": "城市名称"}
                }
            }
        }
    }
]

# ====================== 2. 循环工具调用核心逻辑 ======================
def run_agent_loop(client, model_name: str, user_query: str, max_loop: int = 5) -> str:
    """
    :param client: 大模型客户端(openai/ollama/qwen-openai兼容客户端)
    :param model_name: 模型名称
    :param user_query: 用户原始问题
    :param max_loop: 最大工具调用轮次，防止死循环！非常重要
    :return: 最终回答文本
    """
    messages = [{"role": "user", "content": user_query}]
    loop_count = 0

    while loop_count < max_loop:
        loop_count += 1
        print(f"\n===== 第{loop_count}轮对话 =====")

        # 1. 请求大模型，允许工具调用
        resp = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        msg = resp.choices[0].message

        # 分支1：模型不需要调用工具，直接输出答案，终止循环
        if not msg.tool_calls:
            messages.append(msg.model_dump())
            return msg.content

        # 分支2：模型需要调用工具，执行工具函数
        messages.append(msg.model_dump())
        for tool_call in msg.tool_calls:
            func_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            print(f"调用工具：{func_name}, 参数: {args}")

            # 执行函数
            func = tool_functions[func_name]
            result = func(**args)
            print(f"工具返回结果：{result}")

            # 将工具执行结果添加到上下文，必须固定role格式
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": func_name,
                "content": result
            })

    # 达到最大循环上限，强制让模型总结现有信息输出答案
    final_resp = client.chat.completions.create(
        model=model_name,
        messages=messages
    )
    return final_resp.choices[0].message.content
