"""牛客网拉取脚本。

优化版：
- BeautifulSoup import 提到模块顶层

用法：
    python fetch_nowcoder.py --problem NC16693 --out ./problems/NC16693.md
    python fetch_nowcoder.py --url https://www.nowcoder.com/practice/xxx --out ./problems/
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    Problem,
    Sample,
    clean_html,
    http_get,
    log_err,
    log_ok,
    write_problem_file,
)


NOWCODER_PRACTICE_URL = "https://www.nowcoder.com/practice/{id}"


def fetch_nowcoder(problem_id: str, cookie: str | None = None) -> Problem:
    """拉单题。problem_id 可以是 'NC16693' 或纯数字 questionId。"""
    if problem_id.upper().startswith("NC"):
        qid = problem_id[2:]
    else:
        qid = problem_id

    url = NOWCODER_PRACTICE_URL.format(id=qid)
    resp = http_get(url, cookies=cookie, retry=2)
    soup = BeautifulSoup(resp.text, "lxml")

    title_el = soup.select_one("h1") or soup.select_one(".subject-title")
    title = title_el.get_text(strip=True) if title_el else problem_id

    # 题目主体容器
    body = soup.select_one(".subject-describe") or soup.select_one("#questionDetail") or soup.body
    md, has_imgs, has_form = clean_html(str(body) if body else html, base_url=url)

    samples: list[Sample] = []
    # 牛客样例通常嵌在 <pre> 里，标题前后有"输入"/"输出"
    pre_blocks = body.select("pre") if body else []
    if len(pre_blocks) >= 2:
        # 简单策略：成对解析
        for i in range(0, len(pre_blocks) - 1, 2):
            samples.append(Sample(
                input_text=pre_blocks[i].get_text("\n", strip=False).rstrip("\n"),
                output_text=pre_blocks[i + 1].get_text("\n", strip=False).rstrip("\n"),
            ))

    return Problem(
        problem_id=problem_id.upper(),
        platform="牛客",
        title=title,
        description=md,
        samples=samples,
        tags=[],
        constraints="",
        source_url=url,
        has_images=has_imgs,
        has_formulas=has_form,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取牛客题目")
    parser.add_argument("--problem", help="题号，如 NC16693")
    parser.add_argument("--url", help="题目 URL（任意牛客题）")
    parser.add_argument("--out", required=True)
    parser.add_argument("--cookie", help="牛客 Cookie（私有题用）")
    args = parser.parse_args()

    out_path = Path(args.out)
    if out_path.suffix == "":
        out_path.mkdir(parents=True, exist_ok=True)

    if args.problem:
        prob = fetch_nowcoder(args.problem, cookie=args.cookie)
        target = out_path if out_path.suffix else (out_path / f"{prob.problem_id}.md")
        p = write_problem_file(prob, target)
        log_ok(f"{prob.problem_id} -> {p}")
    elif args.url:
        m = re.search(r"/practice/(\w+)", args.url)
        if not m:
            raise ValueError(f"URL 解析失败: {args.url}")
        pid = "NC" + m.group(1)
        prob = fetch_nowcoder(pid, cookie=args.cookie)
        prob.source_url = args.url
        target = out_path if out_path.suffix else (out_path / f"{pid}.md")
        p = write_problem_file(prob, target)
        log_ok(f"{pid} -> {p}")
    else:
        raise SystemExit("必须指定 --problem 或 --url")


if __name__ == "__main__":
    main()
