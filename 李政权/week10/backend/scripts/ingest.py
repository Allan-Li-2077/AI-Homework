from __future__ import annotations

"""
将 data/raw_texts 下的年报摘录文本切分并写入本地 Chroma。
用法（在 backend 目录）:
  python -m scripts.ingest
  python -m scripts.ingest --reset
"""

import argparse
import re
import sys
from pathlib import Path

# 保证可导入 app
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.services import chroma_store, embedding  # noqa: E402


RAW_DIR = PROJECT_ROOT / "data" / "raw_texts"


def chunk_text(text: str, chunk_size: int = 450, overlap: int = 80) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= chunk_size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        # 尽量在句号处断开
        if end < len(text):
            cut = text.rfind("。", start, end)
            if cut > start + chunk_size // 2:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def parse_filename(path: Path) -> tuple[str, int]:
    # 贵州茅台_2023.txt
    stem = path.stem
    parts = stem.split("_")
    company = parts[0]
    year = int(parts[1]) if len(parts) > 1 else 0
    return company, year


def ingest(reset: bool = False) -> None:
    if not RAW_DIR.exists():
        raise FileNotFoundError(f"未找到知识库目录: {RAW_DIR}")

    files = sorted(RAW_DIR.glob("*.txt"))
    if not files:
        raise FileNotFoundError(f"{RAW_DIR} 下没有 .txt 年报摘录")

    if reset:
        client = chroma_store.get_chroma_client()
        try:
            client.delete_collection(settings.collection_name)
            print(f"已删除旧集合: {settings.collection_name}")
        except Exception:
            pass

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for fp in files:
        company, year = parse_filename(fp)
        content = fp.read_text(encoding="utf-8")
        chunks = chunk_text(content)
        print(f"处理 {fp.name}: {len(chunks)} 个片段")
        for idx, chunk in enumerate(chunks):
            chunk_id = f"{company}_{year}_{idx:04d}"
            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append(
                {
                    "company": company,
                    "year": year,
                    "page": idx + 1,
                    "source_file": fp.name,
                    "doc_type": "annual_report",
                    "section": "摘录",
                }
            )

    print(f"开始向量化 {len(documents)} 条（Embedding: {settings.embedding_model}）...")
    vectors = embedding.embed_texts(documents)
    print("写入 Chroma...")
    # 分批 upsert
    batch = 64
    for i in range(0, len(ids), batch):
        chroma_store.upsert_documents(
            ids=ids[i : i + batch],
            documents=documents[i : i + batch],
            embeddings=vectors[i : i + batch],
            metadatas=metadatas[i : i + batch],
        )
        print(f"  已写入 {min(i + batch, len(ids))}/{len(ids)}")

    print(f"完成。集合文档数: {chroma_store.collection_count()}")
    print(f"Chroma 路径: {settings.chroma_path}")


def main():
    parser = argparse.ArgumentParser(description="年报知识库入库")
    parser.add_argument("--reset", action="store_true", help="重建集合")
    args = parser.parse_args()
    ingest(reset=args.reset)


if __name__ == "__main__":
    main()
