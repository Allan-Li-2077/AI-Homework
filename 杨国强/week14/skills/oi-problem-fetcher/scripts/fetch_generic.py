"""通用抓取器：任意机构 OJ（无专属脚本时使用）。

策略：
- 抓 HTML
- 通用选择器取题面、标题、样例
- 失败时给出警告并保留原始 HTML 片段

优化版：BeautifulSoup import 提到模块顶层

用法：
    python fetch_generic.py --url https://oj.example.com/problem?id=123 --out ./p.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    Problem,
    Sample,
    clean_html,
    http_get,
    log_ok,
    log_warn,
    write_problem_file,
)


def fetch_generic(url: str, cookie: str | None = None) -> Problem:
    resp = http_get(url, cookies=cookie, retry=2)
    soup = BeautifulSoup(resp.text, "lxml")

    title_el = soup.select_one("h1, h2, title")
    title = title_el.get_text(strip=True) if title_el else url

    # 尝试多个常见内容容器
    candidates = [
        "article", ".problem-content", "#problem", ".content",
        ".markdown-body", ".problem", "main", ".container",
    ]
    body = None
    for sel in candidates:
        body = soup.select_one(sel)
        if body and len(body.get_text(strip=True)) > 50:
            break
    if not body:
        body = soup.body

    md, has_imgs, has_form = clean_html(str(body) if body else html, base_url=url)

    # 样例：找 pre 块，按出现顺序成对分
    samples: list[Sample] = []
    pre_blocks = (body.select("pre") if body else []) or soup.find_all("pre")
    if len(pre_blocks) >= 2:
        log_warn(f"通用抓取：从 <pre> 块中按成对提取了 {len(pre_blocks) // 2} 个样例（可能不准确）")
        for i in range(0, len(pre_blocks) - 1, 2):
            samples.append(Sample(
                input_text=pre_blocks[i].get_text("\n", strip=False).rstrip("\n"),
                output_text=pre_blocks[i + 1].get_text("\n", strip=False).rstrip("\n"),
            ))

    return Problem(
        problem_id=url.rsplit("/", 1)[-1].split("?")[0] or "unknown",
        platform="通用 OJ",
        title=title,
        description=md,
        samples=samples,
        tags=[],
        constraints="",
        source_url=url,
        has_images=has_imgs,
        has_formulas=has_form,
        extras={"note": "通用抓取模式，结构可能不精确，建议人工核对"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="通用 OJ 抓取")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--cookie")
    args = parser.parse_args()

    out_path = Path(args.out)
    if not out_path.suffix:
        out_path.mkdir(parents=True, exist_ok=True)

    prob = fetch_generic(args.url, cookie=args.cookie)
    target = out_path if out_path.suffix else (out_path / f"{prob.problem_id}.md")
    p = write_problem_file(prob, target)
    log_ok(f"{prob.problem_id} -> {p}")


if __name__ == "__main__":
    main()
