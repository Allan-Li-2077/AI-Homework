from __future__ import annotations

import hashlib
import math
import re

from openai import OpenAI

from app.config import settings


def _use_mock() -> bool:
    return not settings.has_dashscope()


def _tokenize_embed(text: str, dim: int) -> list[float]:
    """无阿里云密钥时的本地确定性向量，便于离线演示。"""
    tokens = re.findall(r"[\u4e00-\u9fff]{1,2}|[A-Za-z0-9]+", text.lower())
    if not tokens:
        tokens = ["empty"]
    vec = [0.0] * dim
    for tok in tokens:
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        for i in range(0, min(len(h), 16), 2):
            idx = int.from_bytes(h[i : i + 2], "little") % dim
            sign = 1.0 if (h[i] % 2 == 0) else -1.0
            vec[idx] += sign
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def get_embedding_client() -> OpenAI:
    return OpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.embedding_base_url,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if _use_mock():
        return [_tokenize_embed(t, settings.embedding_dim) for t in texts]

    client = get_embedding_client()
    batch_size = 10
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(
            model=settings.embedding_model,
            input=batch,
            dimensions=settings.embedding_dim,
            encoding_format="float",
        )
        ordered = sorted(resp.data, key=lambda x: x.index)
        vectors.extend([item.embedding for item in ordered])
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
