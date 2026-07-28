import json
from typing import Dict, List, Any
from openai import OpenAI

# -------------------------- 1. 工具定义与实现 --------------------------
def get_weather(city: str) -> str:
    """查询城市实时天气"""
    mock_weather = {
        "杭州": "晴，28~35℃，东南风3级，紫外线强",
        "宁波": "多云，27~33℃，微风",
        "上海": "小雨，25~30℃，出门需带伞",
        "北京": "阴天，24~30℃"
    }
    return f"【{city}天气】{mock_weather.get(city, f"无{city}天气数据")}"

tool_mapping = {
    "get_weather": get_weather
}

tool_schema = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询任意城市当日天气",
            "parameters": {
                "type": "object",
                "required": ["city"],
                "properties": {"city": {"type": "string", "description": "城市中文名"}}
            }
        }
    }
]

# -------------------------- 2. 会话管理器：实现多轮对话记忆 --------------------------
class SessionManager:
    def __init__(self):
        # key: 会话id，value: 完整对话消息列表
        self.session_store: Dict[str, List[Dict[str, Any]]] = {}

    def create_session(self, session_id: str):
        """新建空白会话"""
        if session_id not in self.session_store:
            self.session_store[session_id] = []

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """获取会话全部历史消息"""
        return self.session_store.get(session_id, [])

    def append_message(self, session_id: str, msg: Dict[str, Any]):
        """追加一条消息到会话上下文"""
        self.create_session(session_id)
        self.session_store[session_id].append(msg)

    def clear_session(self, session_id: str):
        """清空会话历史（重置对话）"""
        if session_id in self.session_store:
            self.session_store[session_id] = []

# 全局会话实例
session_mgr = SessionManager()

# -------------------------- 3. 带循环工具调用+多轮记忆的Agent核心 --------------------------
def agent_run_loop(
    client: OpenAI,
    session_id: str,
    user_input: str,
    model: str = "Qwen2-7B-Instruct",
    max_tool_loop: int = 5
) -> str:
    """
    整合多轮对话记忆 + 循环工具调用
    :param client: 大模型客户端
    :param session_id: 唯一会话标识，区分不同用户对话
    :param user_input: 用户当前轮输入
    :param model: 模型名称
    :param max_tool_loop: 单次用户提问最大工具调用轮次
    :return: AI最终回复文本
    """
    # 1. 将当前用户输入存入会话记忆
    session_mgr.append_message(session_id, {"role": "user", "content": user_input})
    messages = session_mgr.get_messages(session_id)
    tool_round = 0

    # 2. 工具调用循环：同一轮用户提问可多次调用工具
    while tool_round < max_tool_loop:
        tool_round += 1
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tool_schema,
            tool_choice="auto"
        )
        resp_msg = resp.choices[0].message

        # 分支1：无需调用工具，直接生成回答，存入会话并返回
        if not resp_msg.tool_calls:
            msg_dump = resp_msg.model_dump()
            session_mgr.append_message(session_id, msg_dump)
            return resp_msg.content

        # 分支2：存在工具调用，执行所有工具并回填上下文
        session_mgr.append_message(session_id, resp_msg.model_dump())
        for call in resp_msg.tool_calls:
            func_name = call.function.name
            args = json.loads(call.function.arguments)
            # 执行工具
            func = tool_mapping[func_name]
            tool_result = func(** args)
            # 工具结果写入会话记忆
            session_mgr.append_message(session_id, {
                "role": "tool",
                "tool_call_id": call.id,
                "name": func_name,
                "content": tool_result
            })
        # 更新上下文，下一轮循环判断是否还要继续调用工具
        messages = session_mgr.get_messages(session_id)

    # 达到工具调用上限，强制总结输出
    final_resp = client.chat.completions.create(model=model, messages=messages)
    final_text = final_resp.choices[0].message.content
    session_mgr.append_message(session_id, {"role": "assistant", "content": final_text})
    return final_text

# -------------------------- 4. 测试多轮对话Demo --------------------------
if __name__ == "__main__":
    # 初始化客户端（本地vllm/ollama/通义千问兼容接口均可）
    llm_client = OpenAI(
        base_url="http://127.0.0.1:8000/v1",
        api_key="dummy-key"
    )
    # 固定会话ID，模拟同一个用户持续对话
    sid = "user_001"

    print("===== 多轮对话测试开始 =====")
    # 第一轮提问
    res1 = agent_run_loop(llm_client, sid, "帮我查杭州的天气")
    print(f"AI：{res1}\n")

    # 第二轮连续提问（复用会话记忆，自动追加工具调用）
    res2 = agent_run_loop(llm_client, sid, "再查一下宁波")
    print(f"AI：{res2}\n")

    # 第三轮纯自然问答，不再调用工具
    res3 = agent_run_loop(llm_client, sid, "这两个城市今天哪个更适合出去玩？")
    print(f"AI：{res3}\n")

    # 重置对话（清空历史记忆）
    # session_mgr.clear_session(sid)
