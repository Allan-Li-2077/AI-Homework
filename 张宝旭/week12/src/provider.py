"""Shared OpenAI-compatible provider configuration.

This project can run against SiliconFlow, DeepSeek, or DashScope endpoints.
The helpers below pick a sensible backend from environment variables and keep
chat / embedding setup consistent across the app.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from openai import OpenAI

ProviderKind = Literal["chat", "embed"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOTENV_PATH = PROJECT_ROOT / ".env"

SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _load_dotenv() -> None:
    if not DOTENV_PATH.exists():
        return

    for raw_line in DOTENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    api_key: str
    base_url: str
    chat_model: str
    embed_model: str


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _build_config(kind: ProviderKind) -> ProviderConfig:
    if kind == "chat":
        api_key = _first_env("SILICONFLOW_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Missing API key. Set SILICONFLOW_API_KEY, DEEPSEEK_API_KEY, or DASHSCOPE_API_KEY."
            )

        if os.getenv("SILICONFLOW_API_KEY"):
            return ProviderConfig(
                provider="siliconflow",
                api_key=api_key,
                base_url=os.getenv("SILICONFLOW_BASE_URL", SILICONFLOW_BASE_URL),
                chat_model=os.getenv("CHAT_MODEL", os.getenv("AGENT_MODEL", "deepseek-ai/DeepSeek-V3")),
                embed_model=os.getenv("EMBED_MODEL", "BAAI/bge-m3"),
            )

        if os.getenv("DEEPSEEK_API_KEY"):
            return ProviderConfig(
                provider="deepseek",
                api_key=api_key,
                base_url=os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL),
                chat_model=os.getenv("CHAT_MODEL", os.getenv("AGENT_MODEL", "deepseek-chat")),
                embed_model=os.getenv("EMBED_MODEL", "BAAI/bge-m3"),
            )

        return ProviderConfig(
            provider="dashscope",
            api_key=api_key,
            base_url=os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_BASE_URL),
            chat_model=os.getenv("CHAT_MODEL", os.getenv("AGENT_MODEL", "qwen-max")),
            embed_model=os.getenv("EMBED_MODEL", "text-embedding-v3"),
        )

    api_key = _first_env("SILICONFLOW_API_KEY", "DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing embedding API key. Set SILICONFLOW_API_KEY (recommended) or DASHSCOPE_API_KEY."
        )

    if os.getenv("SILICONFLOW_API_KEY"):
        return ProviderConfig(
            provider="siliconflow",
            api_key=api_key,
            base_url=os.getenv("SILICONFLOW_BASE_URL", SILICONFLOW_BASE_URL),
            chat_model=os.getenv("CHAT_MODEL", os.getenv("AGENT_MODEL", "deepseek-ai/DeepSeek-V3")),
            embed_model=os.getenv("EMBED_MODEL", "BAAI/bge-m3"),
        )

    return ProviderConfig(
        provider="dashscope",
        api_key=api_key,
        base_url=os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_BASE_URL),
        chat_model=os.getenv("CHAT_MODEL", os.getenv("AGENT_MODEL", "qwen-max")),
        embed_model=os.getenv("EMBED_MODEL", "text-embedding-v3"),
    )


def get_provider_config(kind: ProviderKind) -> ProviderConfig:
    return _build_config(kind)


def get_client(kind: ProviderKind) -> OpenAI:
    cfg = get_provider_config(kind)
    return OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)


def get_chat_client() -> OpenAI:
    return get_client("chat")


def get_embed_client() -> OpenAI:
    return get_client("embed")
