"""
从巨潮资讯等公开渠道下载年报 PDF 的辅助脚本（可选）。
因交易所反爬与链接变更频繁，默认提供手工清单；成功下载后可用 pdf_to_text.py 转换。

用法:
  python -m scripts.download_reports
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
PDF_DIR = PROJECT_ROOT / "data" / "raw_pdfs"
MANIFEST = PROJECT_ROOT / "data" / "report_manifest.json"


DEFAULT_MANIFEST = {
    "note": "请将可公开访问的年报 PDF 直链填入 urls。习酒若无独立上市年报，可放入集团披露材料。",
    "reports": [
        {"company": "贵州茅台", "code": "600519", "year": 2022, "url": ""},
        {"company": "贵州茅台", "code": "600519", "year": 2023, "url": ""},
        {"company": "贵州茅台", "code": "600519", "year": 2024, "url": ""},
        {"company": "贵州茅台", "code": "600519", "year": 2025, "url": ""},
        {"company": "五粮液", "code": "000858", "year": 2022, "url": ""},
        {"company": "五粮液", "code": "000858", "year": 2023, "url": ""},
        {"company": "五粮液", "code": "000858", "year": 2024, "url": ""},
        {"company": "五粮液", "code": "000858", "year": 2025, "url": ""},
        {"company": "泸州老窖", "code": "000568", "year": 2022, "url": ""},
        {"company": "泸州老窖", "code": "000568", "year": 2023, "url": ""},
        {"company": "泸州老窖", "code": "000568", "year": 2024, "url": ""},
        {"company": "泸州老窖", "code": "000568", "year": 2025, "url": ""},
        {"company": "习酒", "code": "", "year": 2022, "url": ""},
        {"company": "习酒", "code": "", "year": 2023, "url": ""},
        {"company": "习酒", "code": "", "year": 2024, "url": ""},
        {"company": "习酒", "code": "", "year": 2025, "url": ""},
    ],
}


def ensure_manifest() -> dict:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.exists():
        MANIFEST.write_text(
            json.dumps(DEFAULT_MANIFEST, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"已生成清单: {MANIFEST}，请填写 url 后重跑。")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def download():
    data = ensure_manifest()
    ok, skip = 0, 0
    for item in data.get("reports", []):
        url = (item.get("url") or "").strip()
        company = item["company"]
        year = item["year"]
        target_dir = PDF_DIR / company
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{year}.pdf"
        if not url:
            skip += 1
            continue
        if target.exists():
            print(f"已存在，跳过: {target}")
            ok += 1
            continue
        print(f"下载 {company} {year} ...")
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as r:
                r.raise_for_status()
                with target.open("wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            ok += 1
        except Exception as exc:
            print(f"失败: {company} {year}: {exc}")
    print(f"完成: 成功/已有 {ok}, 无链接跳过 {skip}")


if __name__ == "__main__":
    download()
