"""
LLM 客户端封装：OpenAI 兼容协议指向 DashScope。
"""
from __future__ import annotations

import logging
import os

from openai import OpenAI

log = logging.getLogger("harness.llm")

__all__ = ["LLM"]

_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DEFAULT_MODEL = "qwen-max"


class LLM:
    """对 OpenAI 兼容客户端的薄封装，统一超时与参数。"""

    def __init__(self):
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "DASHSCOPE_API_KEY 环境变量未设置，请先设置后再启动。"
            )
        self.client = OpenAI(
            api_key=api_key,
            base_url=_BASE_URL,
            timeout=60.0,
        )
        self.model = os.getenv("AGENT_MODEL", _DEFAULT_MODEL)
        log.info("LLM ready: model=%s base_url=%s", self.model, _BASE_URL)

    def chat(
        self,
        messages,
        *,
        tools=None,
        tool_choice=None,
        response_format=None,
        temperature=0.0,
        max_tokens=None,
    ):
        """发起一次 chat completion。APIError 上抛，由调用方处理。"""
        kwargs = dict(model=self.model, messages=messages, temperature=temperature)
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if response_format is not None:
            kwargs["response_format"] = response_format
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        return self.client.chat.completions.create(**kwargs)
