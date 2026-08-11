"""LLM 客户端包：调用 OpenAI 兼容的 chat completions 接口。"""

from .client import LLMClient, ChatResult, LLMConfig

__all__ = ["LLMClient", "ChatResult", "LLMConfig"]
