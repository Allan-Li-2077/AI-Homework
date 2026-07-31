from __future__ import annotations

from typing import Protocol

from .config import ModelConfig


class LLMClient(Protocol):
    def complete(self, instructions: str, input_text: str) -> str: ...


class OpenAIResponsesClient:
    """对官方 OpenAI Python SDK 的小型适配层，方便测试时注入 Fake。"""

    def __init__(self, config: ModelConfig | None = None):
        self.config = config or ModelConfig.from_env()
        if not self.config.api_key:
            raise RuntimeError(
                "LLM Skill 需要 OPENAI_API_KEY；也可以向 Harness 注入 llm_client"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("缺少 openai SDK，请执行: python -m pip install -e .") from exc
        kwargs = {"api_key": self.config.api_key}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        self._client = OpenAI(**kwargs)

    def complete(self, instructions: str, input_text: str) -> str:
        response = self._client.responses.create(
            model=self.config.model,
            instructions=instructions,
            input=input_text,
            reasoning={"effort": self.config.reasoning_effort},
        )
        return response.output_text
