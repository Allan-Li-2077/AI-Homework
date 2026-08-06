"""OpenAI 兼容 chat completions 客户端（标准库实现，零依赖）。

支持任意 OpenAI 兼容服务：OpenAI / 智谱 GLM / DeepSeek / Moonshot / 本地 vLLM 等。
配置通过环境变量：
    LLM_API_KEY   API key（必填，未设置时客户端进入"估算模式"）
    LLM_BASE_URL  接口地址，默认 https://api.openai.com/v1
    LLM_MODEL     模型名，默认 gpt-3.5-turbo
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            model=os.getenv("LLM_MODEL", "gpt-3.5-turbo"),
        )

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)


@dataclass
class ChatResult:
    """单次对话结果，含真实 token 用量。"""

    content: str
    prompt_tokens: int      # 输入 token（system + skill + user）
    completion_tokens: int  # 输出 token
    total_tokens: int
    real_usage: bool       # True=API 返回真实用量；False=本地估算


class LLMClient:
    """OpenAI 兼容 chat completions 客户端。"""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_env()

    def chat(self, system: str, user: str, temperature: float = 0.0) -> ChatResult:
        """发起一次对话。返回模型回答与 token 用量。

        - 配置了 API key：调用真实接口，返回 API 报告的真实 token 数
        - 未配置 key：不联网，用本地估算给出 token 数（标注 real_usage=False）
        """
        if self.config.has_key:
            return self._call_api(system, user, temperature)
        return self._estimate(system, user)

    # ---------------- 真实 API 调用 ----------------

    def _call_api(self, system: str, user: str, temperature: float) -> ChatResult:
        url = f"{self.config.base_url}/chat/completions"
        payload = {
            "model": self.config.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        choice = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return ChatResult(
            content=choice,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            real_usage=True,
        )

    # ---------------- 本地估算 fallback ----------------

    def _estimate(self, system: str, user: str) -> ChatResult:
        """无 API key 时的粗略 token 估算。

        估算规则（近似 GPT BPE）：
        - 中文字符按 1.5 token/字
        - 其他字符按 1 token / 4 字符
        """
        prompt_tokens = self._estimate_text(system) + self._estimate_text(user)
        # 假设模型输出"调用 weather-query 工具 + 参数 JSON"，约 20 token
        completion_tokens = 20
        return ChatResult(
            content='{"skill":"weather-query","location":"<推断>"}',
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            real_usage=False,
        )

    @staticmethod
    def _estimate_text(text: str) -> int:
        cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other = len(text) - cjk
        return int(cjk * 1.5 + other / 4)
