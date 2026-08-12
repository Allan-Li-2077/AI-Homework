"""洛谷拉取脚本：单题或区间。

用法：
    python fetch_luogu.py --problem P1000 --out ./problems/P1000.md
    python fetch_luogu.py --range P1000-P1010 --out ./problems/
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    Problem,
    Sample,
    clean_html,
    http_get,
    iter_range,
    log_err,
    log_ok,
    log_warn,
    parse_range,
    write_problem_file,
)

# 预编译正则（模块加载时一次，零调用开销）
_RE_PID = re.compile(r"^(?:P|B|U)\d{1,6}$", re.IGNORECASE)
_RE_AT  = re.compile(r"^AT_\w+$",            re.IGNORECASE)


LUOGU_PROBLEM_URL = "https://www.luogu.com.cn/problem/{pid}"
LUOGU_API_URL = "https://www.luogu.com.cn/api/problem/detail"


def fetch_luogu_one(pid: str, cookie: str | None = None) -> Problem:
    """拉取洛谷单题。优先 API，失败回退 HTML。"""
    pid_upper = pid.upper()
    if not _RE_PID.match(pid_upper) and not _RE_AT.match(pid_upper):
        raise ValueError(f"不是合法的洛谷题号: {pid}")

    headers = {
        "Referer": LUOGU_PROBLEM_URL.format(pid=pid_upper),
        "x-luogu-type": "content-only",
        "Accept": "application/json",
    }
    try:
        resp = http_get(
            LUOGU_API_URL,
            headers=headers,
            cookies=cookie,
            retry=2,
        )
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"API 返回非 200: code={data.get('code')} data={data}")
        result = data["data"]
        return parse_luogu_api(pid_upper, result)
    except Exception as api_err:
        log_warn(f"API 失败，回退 HTML 抓取: {api_err}")
        return fetch_luogu_html(pid_upper, cookie)


def parse_luogu_api(pid: str, result: dict) -> Problem:
    """解析洛谷 API 返回的 JSON。"""
    title = result.get("title", "").strip()
    desc_parts = []
    if result.get("background"):
        desc_parts.append(f"### 题目背景\n\n{result['background']}")
    if result.get("description"):
        desc_parts.append(f"### 问题描述\n\n{result['description']}")
    if result.get("inputFormat"):
        desc_parts.append(f"### 输入格式\n\n{result['inputFormat']}")
    if result.get("outputFormat"):
        desc_parts.append(f"### 输出格式\n\n{result['outputFormat']}")
    description = "\n\n".join(desc_parts)

    samples = []
    for i in range(1, 20):
        sin = result.get(f"sampleInput{i}") or result.get(f"sampleInput[{i}]")
        sout = result.get(f"sampleOutput{i}") or result.get(f"sampleOutput[{i}]")
        if not sin or not sout:
            break
        samples.append(Sample(input_text=sin, output_text=sout))

    constraints_parts = []
    if result.get("hint"):
        constraints_parts.append(f"### 提示\n\n{result['hint']}")
    if result.get("limit"):
        constraints_parts.append(f"### 数据范围\n\n{result['limit']}")
    constraints = "\n\n".join(constraints_parts)

    tags = []
    raw_tags = result.get("tags") or []
    if isinstance(raw_tags, list):
        for t in raw_tags:
            if isinstance(t, dict):
                tags.append(t.get("name", ""))
            else:
                tags.append(str(t))
    tags = [t for t in tags if t]

    return Problem(
        problem_id=pid,
        platform="洛谷",
        title=title,
        description=description,
        samples=samples,
        tags=tags,
        constraints=constraints,
        source_url=LUOGU_PROBLEM_URL.format(pid=pid),
        has_images="<img" in description or "![" in description,
        has_formulas=("$" in description) or ("\\(" in description) or ("mathjax" in description.lower()),
    )


def fetch_luogu_html(pid: str, cookie: str | None) -> Problem:
    """回退方案：直接抓 HTML。"""
    url = LUOGU_PROBLEM_URL.format(pid=pid)
    resp = http_get(url, cookies=cookie, retry=2)
    html = resp.text

    soup = type("S", (), {})  # placeholder
    from bs4 import BeautifulSoup
    sp = BeautifulSoup(html, "lxml")

    title_el = sp.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else pid

    # 洛谷题目主体在 .main-container 或 article 内
    article = sp.select_one("article") or sp.select_one(".problem-card") or sp.body
    md, has_imgs, has_form = clean_html(str(article) if article else html, base_url=url)

    return Problem(
        problem_id=pid,
        platform="洛谷",
        title=title,
        description=md,
        samples=[],
        tags=[],
        constraints="",
        source_url=url,
        has_images=has_imgs,
        has_formulas=has_form,
        extras={"note": "HTML 回退模式，样例和标签未解析；建议人工补全"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取洛谷题目")
    parser.add_argument("--problem", help="单题题号，如 P1000")
    parser.add_argument("--range", dest="rng", help="题号区间，如 P1000-P1010")
    parser.add_argument("--out", required=True, help="输出文件或目录")
    parser.add_argument("--cookie", help="洛谷 Cookie（私密题用）")
    parser.add_argument("--delay", type=float, default=1.0, help="请求间隔（秒）")
    args = parser.parse_args()

    cookie = args.cookie or None

    if args.problem:
        ids = [args.problem.upper()]
    elif args.rng:
        prefix, start, end = parse_range(args.rng)
        ids = list(iter_range(prefix, start, end))
    else:
        parser.error("必须指定 --problem 或 --range")

    out_path = Path(args.out)
    is_dir = out_path.is_dir() or args.rng or not out_path.suffix
    if is_dir:
        out_path.mkdir(parents=True, exist_ok=True)

    success, failed = 0, []
    for pid in ids:
        try:
            prob = fetch_luogu_one(pid, cookie=cookie)
            target = (out_path / f"{pid}.md") if is_dir else out_path
            p = write_problem_file(prob, target)
            log_ok(f"{pid} -> {p}")
            success += 1
        except Exception as e:
            log_err(f"{pid}: {e}")
            failed.append(pid)
        if len(ids) > 1:
            time.sleep(args.delay)

    print(f"\nDone: {success} succeeded, {len(failed)} failed", file=sys.stderr)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
