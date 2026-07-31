from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    """OpenAI Responses API 配置。环境变量优先，避免密钥进入仓库。"""

    model: str = "gpt-5.6-luna"
    api_key: str | None = None
    base_url: str | None = None
    reasoning_effort: str = "low"

    @classmethod
    def from_env(cls) -> "ModelConfig":
        return cls(
            model=os.getenv("SKILL_HARNESS_MODEL", "gpt-5.6-luna"),
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            reasoning_effort=os.getenv("SKILL_HARNESS_REASONING_EFFORT", "low"),
        )
