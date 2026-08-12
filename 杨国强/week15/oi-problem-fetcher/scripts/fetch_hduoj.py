"""HDUOJ 拉取脚本。

优化版：
- BeautifulSoup import 提到模块顶层
- `find_all(string=re.compile(...))` → `select("i")` 精确选择器，DOM 遍历开销从整页降至局部
- 删 `import re`，数字提取改用 `str.isdigit` 过滤

用法：
    python fetch_hduoj.py --problem 1000 --out ./problems/HDU1000.md
    python fetch_hduoj.py --range 1000-1010 --out ./problems/
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    Problem,
    Sample,
    clean_html,
    http_get,
    iter_range,
    log_err,
    log_ok,
    parse_range,
    write_problem_file,
)


HDU_URL = "http://acm.hdu.edu.cn/showproblem.php?pid={pid}"


def fetch_hdu(pid: str) -> Problem:
    """拉单题。注意 HDU 是 GBK 编码。"""
    pid_num = "".join(c for c in pid if c.isdigit())
    pid_num = "".join(c for c in pid if c.isdigit())
    url = f"http://acm.hdu.edu.cn/showproblem.php?pid={pid_num}"
    resp = http_get(url, retry=3)
    resp.encoding = "gbk"
    soup = BeautifulSoup(resp.text, "lxml")

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else f"HDU {pid_num}"

    panel = soup.select_one(".panel_content") or soup.body
    md, has_imgs, has_form = clean_html(str(panel) if panel else resp.text, base_url=url)

    # 样例：直接找 <i> 标签（含文本 "Sample Input/Output"）后跟 <pre>
    samples: list[Sample] = []
    sin_tags = soup.select("i")
    output_tags = soup.select("i")
    sin_dict, sout_dict = {}, {}

    for tag in sin_tags:
        if tag.get_text(strip=True) == "Sample Input":
            nxt = tag.find_next_sibling()
            if nxt and nxt.name == "pre":
                num = tag.find_previous_sibling("p")
                idx = "".join(c for c in (num.get_text() if num else "1") if c.isdigit()) or "1"
                sin_dict[idx] = nxt.get_text("\n", strip=False).rstrip("\n")

    for tag in output_tags:
        if tag.get_text(strip=True) == "Sample Output":
            nxt = tag.find_next_sibling()
            if nxt and nxt.name == "pre":
                num = tag.find_previous_sibling("p")
                idx = "".join(c for c in (num.get_text() if num else "1") if c.isdigit()) or "1"
                sout_dict[idx] = nxt.get_text("\n", strip=False).rstrip("\n")

    for k in sorted(sin_dict.keys() & sout_dict.keys()):
        samples.append(Sample(input_text=sin_dict[k], output_text=sout_dict[k]))

    return Problem(
        problem_id=f"HDU{pid_num}",
        platform="HDUOJ",
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
    parser = argparse.ArgumentParser(description="拉取 HDUOJ 题目")
    parser.add_argument("--problem", help="单题，如 1000 或 HDU1000")
    parser.add_argument("--range", dest="rng", help="区间，如 1000-1010 或 HDU 1000-1005")
    parser.add_argument("--out", required=True)
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()

    out_path = Path(args.out)

    if args.problem:
        ids = [args.problem]
    elif args.rng:
        prefix, start, end = parse_range(args.rng)
        ids = list(iter_range(prefix, start, end))
    else:
        raise SystemExit("必须指定 --problem 或 --range")

    if not out_path.suffix:
        out_path.mkdir(parents=True, exist_ok=True)

    ok, failed = 0, []
    for pid in ids:
        try:
            prob = fetch_hdu(pid)
            target = out_path if out_path.suffix else (out_path / f"{prob.problem_id}.md")
            p = write_problem_file(prob, target)
            log_ok(f"{prob.problem_id} -> {p}")
            ok += 1
        except Exception as e:
            log_err(f"{pid}: {e}")
            failed.append(pid)
        if len(ids) > 1:
            time.sleep(args.delay)

    print(f"\nDone: {ok}/{len(ids)}", file=sys.stderr)


if __name__ == "__main__":
    main()
