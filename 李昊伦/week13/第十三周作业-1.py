"""
LLM 提供商配置 — 自动检测环境变量，支持 DashScope / DeepSeek

用法：
    from src.llm_config import get_chat_client
    client, model = get_chat_client()
"""

import os
from openai import OpenAI

PROVIDERS = {
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "chat_model": "qwen-max",
        "display": "通义千问 qwen-max (DashScope)",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "chat_model": "deepseek-chat",
        "display": "DeepSeek Chat",
    },
}


def get_provider() -> str:
    if os.getenv("DASHSCOPE_API_KEY"):
        return "qwen"
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek"
    raise EnvironmentError(
        "未找到 API Key。请设置 DASHSCOPE_API_KEY 或 DEEPSEEK_API_KEY 环境变量。"
    )


def get_chat_client() -> tuple[OpenAI, str]:
    provider = get_provider()
    cfg = PROVIDERS[provider]
    api_key = os.getenv(cfg["api_key_env"])
    client = OpenAI(api_key=api_key, base_url=cfg["base_url"])
    model = os.getenv("AGENT_MODEL", cfg["chat_model"])
    return client, model


def current_model_info() -> dict:
    provider = get_provider()
    cfg = PROVIDERS[provider]
    return {"provider": provider, "display": cfg["display"]}
