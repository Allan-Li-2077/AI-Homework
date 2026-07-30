"""
LLM 配置模块 — 统一管理 LLM 提供商

支持 DeepSeek（默认）和 Qwen/DashScope 两种后端，
通过环境变量 LLM_PROVIDER 切换。

使用方式：
    from .llm_config import get_chat_client, current_model_info
    client, model = get_chat_client()      # 返回 (OpenAI client, model_name)
    info = current_model_info()            # 返回当前使用的模型信息

环境变量：
    LLM_PROVIDER        deepseek(默认) 或 qwen
    DEEPSEEK_API_KEY    DeepSeek API Key
    DASHSCOPE_API_KEY   DashScope API Key
"""

import os
import logging

logger = logging.getLogger(__name__)

# ── 提供商配置 ──────────────────────────────────────────────────────────

PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "chat_model": "deepseek-chat",
        "display": "DeepSeek V3",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "chat_model": "qwen-plus",
        "display": "Qwen Plus (DashScope)",
        "api_key_env": "DASHSCOPE_API_KEY",
    },
}

DEFAULT_PROVIDER = "deepseek"

# ── 公开接口 ────────────────────────────────────────────────────────────

def get_chat_client():
    """
    获取 LLM 对话客户端。

    Returns:
        (openai.OpenAI, model_name: str)

    Raises:
        EnvironmentError: API Key 未设置时抛出
    """
    provider_name = os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER).lower()
    if provider_name not in PROVIDERS:
        logger.warning(f"未知的 LLM 提供商 '{provider_name}'，回退到 {DEFAULT_PROVIDER}")
        provider_name = DEFAULT_PROVIDER

    cfg = PROVIDERS[provider_name]
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        raise EnvironmentError(
            f"未设置 {cfg['api_key_env']} 环境变量。\n"
            f"请执行: export {cfg['api_key_env']}=your-api-key\n"
            f"或切换提供商: export LLM_PROVIDER=qwen"
        )

    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("请安装 openai: pip install openai>=1.0.0")

    client = OpenAI(api_key=api_key, base_url=cfg["base_url"])
    return client, cfg["chat_model"]


def current_model_info() -> dict:
    """返回当前使用的模型信息"""
    provider_name = os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER).lower()
    if provider_name not in PROVIDERS:
        provider_name = DEFAULT_PROVIDER
    cfg = PROVIDERS[provider_name]
    return {
        "provider": provider_name,
        "model": cfg["chat_model"],
        "display": cfg["display"],
        "api_key_env": cfg["api_key_env"],
    }


def is_available() -> bool:
    """检查 LLM 是否可用（API Key 是否已设置）"""
    try:
        get_chat_client()
        return True
    except EnvironmentError:
        return False
