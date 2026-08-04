"""
Layer 4 语义记忆：FAISS 向量库（记忆条目 Embedding + 语义检索）

教学重点：
  1. 为什么需要语义检索：MEMORY.md 里的记忆条目可能很多，不能全塞进 Context
  2. 增量更新：Memory Flush 后只向量化新增条目，不重建全量索引
  3. 余弦相似度检索：归一化内积 = 余弦相似度

使用方式：
  from src.vector_store import VectorStore
  vs = VectorStore()
  vs.add_entries([{"id": "entry_1", "content": "用户喜欢喝咖啡", "date": "2026-05-08"}])
  results = vs.search("饮品偏好", top_k=3)

依赖：
  pip install faiss-cpu openai
  export DASHSCOPE_API_KEY="sk-xxx"
"""

import os
import json
import pickle
import logging
import numpy as np
from pathlib import Path
from openai import OpenAI

INDEX_DIR = Path(__file__).parent.parent / "data" / "vector_index"
INDEX_FILE = INDEX_DIR / "memory.faiss"
META_FILE = INDEX_DIR / "memory_meta.pkl"

# EMBEDDING_MODEL = "text-embedding-v3"
# BATCH_SIZE = 10  # DashScope 单批上限

# def _get_client() -> OpenAI:
#     return OpenAI(
#         api_key=os.getenv("DASHSCOPE_API_KEY"),
#         base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
#     )

# ── Embedding 配置（本地 BGE 模型）───────────────────────────────────────────
EMBED_PROVIDER      = "local"                     # 本地 BGE 模型
EMBED_MODEL_NAME    = "bge-large-zh-v1.5"         # BGE 中文 small 模型
EMBED_DIM           = 1024
EMBED_BATCH_SIZE    = 32                          # MPS 稳定批次大小（M4 32GB可到128）
EMBED_DEVICE        = "mps"                       # MPS 加速（M4 原生支持，比 CPU 快 2~3x）

# BGE 模型路径（本地 embedding）
BGE_EMBED_MODEL_PATH  = Path("/Users/wangqilin/个人/学习/pretrain_models/bge-small-zh-v1.5")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 本地 BGE Embedding ────────────────────────────────────────────────────────

def _get_embedding_model():
    """加载本地 BGE 模型（单例，M4 用 MPS 加速）。"""
    from sentence_transformers import SentenceTransformer
    import torch

    model_path = str(BGE_EMBED_MODEL_PATH) if BGE_EMBED_MODEL_PATH.exists() else EMBED_MODEL_NAME
    logger.info(f"加载 Embedding 模型: {model_path}")

    if EMBED_DEVICE == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
    else:
        device = EMBED_DEVICE

    model = SentenceTransformer(model_path, device=device)
    logger.info(f"Embedding 模型加载完成 [设备: {device}, 维度: {model.get_embedding_dimension()}]")
    return model

def _embed_query(query: str) -> np.ndarray:
    # BGE 模型：query 需要加前缀以区分 document embedding
    vec = _get_embedding_model().encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    return vec.astype("float32")


# def _embed_texts(texts: list[str]) -> np.ndarray:
#     """批量 Embedding，返回 (N, dim) float32 数组"""
#     client = _get_client()
#     all_vectors = []
#     for i in range(0, len(texts), BATCH_SIZE):
#         batch = texts[i: i + BATCH_SIZE]
#         resp = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
#         vecs = [item.embedding for item in resp.data]
#         all_vectors.extend(vecs)
#     arr = np.array(all_vectors, dtype=np.float32)
#     # L2 归一化 → 内积 = 余弦相似度
#     norms = np.linalg.norm(arr, axis=1, keepdims=True)
#     norms = np.where(norms == 0, 1.0, norms)
#     return arr / norms

def _embed_texts(texts: list[str], show_progress: bool = True) -> np.ndarray:
    """用本地 BGE 模型批量计算 embedding，返回 L2 归一化后的 float32 数组。"""
    model = _get_embedding_model()

    all_embeddings = []
    total_batches = (len(texts) + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE

    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        batch_idx = i // EMBED_BATCH_SIZE + 1

        if show_progress and (batch_idx % 20 == 0 or batch_idx == 1):
            logger.info(f"  Embedding 进度: {batch_idx}/{total_batches} 批")

        # BGE 模型推荐对 query 加前缀；这里对文档 embedding 不加前缀
        vecs = model.encode(
            batch,
            normalize_embeddings=True,   # L2 归一化
            show_progress_bar=False,
            batch_size=EMBED_BATCH_SIZE,
        )
        all_embeddings.append(vecs)

    embeddings = np.vstack(all_embeddings).astype("float32")
    logger.info(f"Embedding 完成: {embeddings.shape}")
    return embeddings


class VectorStore:
    def __init__(self, index_dir: Path = INDEX_DIR):
        self.index_dir = index_dir
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.index = None
        self.metadata: list[dict] = []  # 与 faiss 行号一一对应
        self._load()

    # ── 持久化 ────────────────────────────────────────────────────────────────

    def _load(self):
        if INDEX_FILE.exists() and META_FILE.exists():
            import faiss
            self.index = faiss.read_index(str(INDEX_FILE))
            with open(META_FILE, "rb") as f:
                self.metadata = pickle.load(f)

    def _save(self):
        import faiss
        if self.index is not None:
            faiss.write_index(self.index, str(INDEX_FILE))
        with open(META_FILE, "wb") as f:
            pickle.dump(self.metadata, f)

    # ── 写入 ──────────────────────────────────────────────────────────────────

    def add_entries(self, entries: list[dict]) -> int:
        """
        向量化并写入记忆条目。
        entries 格式：[{"id": str, "content": str, "category": str, "date": str}]
        返回新增条目数。
        """
        import faiss
        if not entries:
            return 0

        texts = [e["content"] for e in entries]
        vectors = _embed_texts(entries)
        dim = vectors.shape[1]

        if self.index is None:
            self.index = faiss.IndexFlatIP(dim)  # 内积索引（L2 归一化后等于余弦）

        self.index.add(vectors)
        self.metadata.extend(entries)
        self._save()
        return len(entries)

    def rebuild_from_entries(self, entries: list[dict]):
        """从零重建索引（Compaction 后使用）"""
        import faiss
        self.index = None
        self.metadata = []
        if entries:
            self.add_entries(entries)

    # ── 查询 ──────────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """
        语义搜索，返回最相关的 top_k 条记忆。
        返回格式：[{"score": float, "content": str, "category": str, "date": str, ...}]
        """
        if self.index is None or self.index.ntotal == 0:
            return []
        q_vec = _embed_query(query)
        k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(q_vec, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            item = dict(self.metadata[idx])
            item["score"] = float(score)
            results.append(item)
        return results

    # ── 统计 ──────────────────────────────────────────────────────────────────

    @property
    def total_entries(self) -> int:
        return self.index.ntotal if self.index else 0

    def get_all_entries(self) -> list[dict]:
        return list(self.metadata)
