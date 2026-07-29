"""extract_pdf_text - 提取 PDF 全部文本页。

依赖: PyPDF2 (pip install PyPDF2)
渐进式约定: PyPDF2 在 run() 内部局部 import。
"""
import os
from typing import Any, Dict, List

SKILL_META: Dict[str, Any] = {
    "name": "extract_pdf_text",
    "description": "提取 PDF 全部文本页",
    "category": "document",
    "params": {
        "input_path": {
            "type": "str",
            "required": True,
            "description": "输入 PDF 路径",
        },
        "page_range": {
            "type": "str",
            "required": False,
            "default": "all",
            "description": "页码范围，如 '1-3' 或 'all'（1-based，闭区间）",
        },
        "output_path": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "保存为 txt 的路径；不填则把文本放在返回值中",
        },
    },
    "dependencies": ["PyPDF2"],
}


def _parse_page_range(page_range: str, total: int) -> List[int]:
    """把 '1-3' / '2' / 'all' 解析为 0-based 页索引列表。"""
    page_range = (page_range or "all").strip().lower()
    if page_range in ("all", "*"):
        return list(range(total))
    # 形如 "1-3"
    if "-" in page_range:
        start_s, end_s = page_range.split("-", 1)
        start = int(start_s)
        end = int(end_s)
        # 转 0-based，闭区间
        return list(range(start - 1, end))
    # 单页
    return [int(page_range) - 1]


def run(**kwargs) -> Dict[str, Any]:
    """提取 PDF 文本。返回文本字符串或保存的 txt 路径。"""
    from PyPDF2 import PdfReader

    input_path = kwargs["input_path"]
    page_range = kwargs.get("page_range", "all")
    output_path = kwargs.get("output_path")

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"输入 PDF 不存在: {input_path}")

    reader = PdfReader(input_path)
    total = len(reader.pages)
    page_indices = _parse_page_range(page_range, total)

    text_parts: List[str] = []
    for i in page_indices:
        if 0 <= i < total:
            page_text = reader.pages[i].extract_text() or ""
            text_parts.append(page_text)
    text = "\n\n".join(text_parts)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        return {
            "output_path": output_path,
            "text_length": len(text),
            "pages_extracted": len(page_indices),
        }

    return {
        "text": text,
        "text_length": len(text),
        "pages_extracted": len(page_indices),
    }
