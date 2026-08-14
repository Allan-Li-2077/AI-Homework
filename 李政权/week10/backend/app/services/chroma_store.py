from __future__ import annotations

from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings


_client: chromadb.PersistentClient | None = None


def get_chroma_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_documents(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict[str, Any]],
) -> None:
    collection = get_collection()
    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def query_similar(
    query_embedding: list[float],
    top_k: int,
    where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    collection = get_collection()
    kwargs: dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where
    return collection.query(**kwargs)


def collection_count() -> int:
    try:
        return get_collection().count()
    except Exception:
        return 0
