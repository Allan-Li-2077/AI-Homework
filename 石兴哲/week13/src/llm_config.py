"""
LLM 提供商统一配置

切换方式（环境变量）：
  LLM_PROVIDER=deepseek    # 默认，使用 DeepSeek deepseek-v4-flash
  LLM_PROVIDER=qwen        # 使用 DashScope qwen-plus

对应 API Key：
  DEEPSEEK_API_KEY=sk-xxx   （deepseek）
  DASHSCOPE_API_KEY=sk-xxx  （qwen）

使用方式：
  from src.llm_config import get_chat_client
  client, model = get_chat_client()
"""

import os
from openai import OpenAI

PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "chat_model": "deepseek-v4-flash",
        "display_name": "DeepSeek V4 Flash",
    },
    "qwen": {
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "chat_model": "qwen-plus",
        "display_name": "Qwen Plus (DashScope)",
    },
}


def get_provider() -> str:
    return os.getenv("LLM_PROVIDER", "deepseek").lower()


def get_chat_client() -> tuple[OpenAI, str]:
    """返回 (client, model_name)，由 LLM_PROVIDER 环境变量决定"""
    provider = get_provider()
    if provider not in PROVIDERS:
        raise ValueError(f"未知 LLM_PROVIDER='{provider}'，可选：{list(PROVIDERS)}")
    cfg = PROVIDERS[provider]
    api_key = os.getenv(cfg["api_key_env"])
    if not api_key:
        raise EnvironmentError(
            f"使用 {cfg['display_name']} 需要设置环境变量 {cfg['api_key_env']}"
        )
    client = OpenAI(api_key=api_key, base_url=cfg["base_url"])
    return client, cfg["chat_model"]


def current_model_info() -> dict:
    """返回当前配置的模型信息"""
    provider = get_provider()
    cfg = PROVIDERS.get(provider, PROVIDERS["deepseek"])
    return {
        "provider": provider,
        "model": cfg["chat_model"],
        "display": cfg["display_name"],
    }
