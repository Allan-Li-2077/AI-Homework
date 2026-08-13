from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent


class Settings(BaseSettings):
    """密钥优先从系统环境变量读取：DEEPSEEK_API_KEY / DASHSCOPE_API_KEY。"""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    dashscope_api_key: str = ""
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024

    chroma_path: str = str(PROJECT_ROOT / "data" / "chroma")
    collection_name: str = "liquor_annual_reports"

    rag_top_k: int = 6
    rag_score_threshold: float = 0.35

    host: str = "0.0.0.0"
    port: int = 8000

    allowed_companies: tuple[str, ...] = (
        "贵州茅台",
        "五粮液",
        "泸州老窖",
        "习酒",
    )

    @field_validator("deepseek_api_key", "dashscope_api_key", mode="before")
    @classmethod
    def _coerce_secret(cls, v):
        if v is None:
            return ""
        return str(v).strip()

    def has_deepseek(self) -> bool:
        return bool(self.deepseek_api_key)

    def has_dashscope(self) -> bool:
        return bool(self.dashscope_api_key)


settings = Settings()
