"""
将 data/raw_pdfs/{公司}/{年}.pdf 转为 data/raw_texts/{公司}_{年}.txt
用法: python -m scripts.pdf_to_text
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

PDF_DIR = PROJECT_ROOT / "data" / "raw_pdfs"
OUT_DIR = PROJECT_ROOT / "data" / "raw_texts"


def convert():
    try:
        import fitz  # pymupdf
    except ImportError as exc:
        raise SystemExit("请先安装 pymupdf: pip install pymupdf") from exc

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = list(PDF_DIR.rglob("*.pdf"))
    if not pdfs:
        print(f"未找到 PDF: {PDF_DIR}")
        return

    for pdf in pdfs:
        company = pdf.parent.name
        year = pdf.stem
        out = OUT_DIR / f"{company}_{year}.txt"
        doc = fitz.open(pdf)
        parts = []
        for page in doc:
            parts.append(page.get_text("text"))
        text = "\n".join(parts).strip()
        out.write_text(text, encoding="utf-8")
        print(f"写出 {out} ({len(text)} 字)")


if __name__ == "__main__":
    convert()
