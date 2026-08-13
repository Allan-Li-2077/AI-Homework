"""
DeepSeek API 客户端 - 同步版本（线程内直接调用，无 async 依赖）
"""
import os
import json
import httpx


def llm_chat_sync(
    system: str,
    user: str,
    temperature: float = 0.0,
    max_tokens: int = 512,
    stop: list = None,
) -> str:
    """
    同步单轮 LLM 对话。用于 ReAct 循环在线程内直接调用。
    stop: ReAct 用 ["Observation:"] 截断，LLM 只输出 Thought/Action/Action Input
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise EnvironmentError("请设置 DEEPSEEK_API_KEY 环境变量")

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if stop:
        payload["stop"] = stop

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            "https://api.deepseek.com/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# 保留 async 版本（流式 SSE 展示用）
async def llm_chat_async(prompt: str, system_prompt: str = None,
                          temperature: float = 0.7, max_tokens: int = 2048) -> str:
    """异步非流式调用（SimpleReActLoop 评估用）"""
    import httpx
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": "deepseek-chat", "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
