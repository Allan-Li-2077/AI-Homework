"""Codeforces 拉取脚本：单题、单场、题号区间。

优化版：
- 每题只发 1 次 HTTP 请求（描述+样例一次拿），而不是原来每题 2 次
- 整场比赛用 ThreadPoolExecutor 并行拉题（网速允许下约 5x 提速）

用法：
    python fetch_codeforces.py --problem 1800A --out ./cf/1800A.md
    python fetch_codeforces.py --contest 1800 --out ./cf/round1800/
    python fetch_codeforces.py --range 1800A-1800E --contest 1800 --out ./cf/
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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


CF_HTML_PROBLEM = "https://codeforces.com/problemset/problem/{cid}/{idx}"


def _fetch_problem_html(cid: int, idx: str) -> tuple[str, list[Sample], bool, bool]:
    """一次 HTTP 请求拿完题面描述和所有样例。

    Returns: (description_md, samples, has_images, has_formulas)
    """
    url = CF_HTML_PROBLEM.format(cid=cid, idx=idx)
    resp = http_get(url, retry=2)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "lxml")

    # 题面主体
    stmt = soup.select_one(".problem-statement")
    if not stmt:
        return f"（无法定位题面 div，请手动核对 {url}）", [], False, False

    desc_raw = stmt.get_text("\n", strip=False)
    md, has_imgs, has_form = clean_html(str(stmt), base_url=url)

    # 样例
    samples: list[Sample] = []
    for blk in soup.select(".sample-test"):
        inp = blk.select_one(".input pre")
        out = blk.select_one(".output pre")
        if inp and out:
            samples.append(Sample(
                input_text=inp.get_text("\n", strip=False).rstrip("\n"),
                output_text=out.get_text("\n", strip=False).rstrip("\n"),
            ))

    return md, samples, has_imgs, has_form


def fetch_contest(contest_id: int, lang: str = "en", max_workers: int = 5) -> list[Problem]:
    """通过 API 拿到题目元信息，然后用 ThreadPoolExecutor 并行抓题面（每题 1 次请求）。

    max_workers：并发数，建议 3-8，太高会被 CF 限流。
    """
    import requests
    # API 拿元信息（rating / tags / 标题）
    resp = http_get(
        f"https://codeforces.com/api/contest.standings?contestId={contest_id}&lang={lang}",
        retry=3,
    )
    data = resp.json()
    if data.get("status") != "OK":
        raise RuntimeError(f"CF API error: {data.get('comment')}")

    problem_meta = {p["index"]: p for p in data["result"]["problems"]}

    def build_one(meta: dict) -> Problem:
        idx = meta["index"]
        desc_md, samples, has_imgs, has_form = _fetch_problem_html(contest_id, idx)
        return Problem(
            problem_id=f"{contest_id}{idx}",
            platform="Codeforces",
            title=meta.get("name", idx),
            description=desc_md,
            samples=samples,
            tags=meta.get("tags", []),
            constraints=f"**Rating**: {meta.get('rating', '')}" if meta.get("rating") else "",
            source_url=CF_HTML_PROBLEM.format(cid=contest_id, idx=idx),
            has_images=has_imgs,
            has_formulas=has_form,
        )

    problems: list[Problem] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(build_one, m): m for m in data["result"]["problems"]}
        for fut in as_completed(futures):
            m = futures[fut]
            try:
                problems.append(fut.result())
            except Exception as e:
                log_err(f"{contest_id}{m['index']}: {e}")
                problems.append(Problem(
                    problem_id=f"{contest_id}{m['index']}",
                    platform="Codeforces",
                    title=m.get("name", m["index"]),
                    description=f"（拉取失败：{e}）\n\n请手动访问 {CF_HTML_PROBLEM.format(cid=contest_id, idx=m['index'])}",
                    samples=[], tags=[], source_url=CF_HTML_PROBLEM.format(cid=contest_id, idx=m["index"]),
                ))
            time.sleep(0.3)  # 控制并发节奏，避免 CF 限流

    # 按字母顺序排（CF API 返回顺序不保证）
    problems.sort(key=lambda p: p.problem_id)
    return problems


def fetch_problem_one(prob_id: str) -> Problem:
    """拉单题，如 '1800A'。"""
    import re
    m = re.match(r"^(\d+)([A-Z]\d?)$", prob_id)
    if not m:
        raise ValueError(f"非法 CF 题号: {prob_id}")
    cid, idx = int(m.group(1)), m.group(2)
    desc_md, samples, has_imgs, has_form = _fetch_problem_html(cid, idx)
    return Problem(
        problem_id=prob_id,
        platform="Codeforces",
        title=prob_id,
        description=desc_md,
        samples=samples,
        tags=[],
        constraints="",
        source_url=CF_HTML_PROBLEM.format(cid=cid, idx=idx),
        has_images=has_imgs,
        has_formulas=has_form,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取 Codeforces 题目")
    parser.add_argument("--problem", help="单题，如 1800A")
    parser.add_argument("--contest", type=int, help="整场比赛 contestId，如 1800")
    parser.add_argument("--range", dest="rng", help="字母区间，如 1800A-1800E（需同时指定 --contest）")
    parser.add_argument("--out", required=True)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--workers", type=int, default=5, help="并行并发数（整场比赛时使用）")
    args = parser.parse_args()

    out_path = Path(args.out)

    if args.contest and args.rng:
        import re, string
        m = re.match(r"^(\d+)([A-Z])-(\d+)?([A-Z])$", args.rng)
        if not m:
            raise ValueError(f"无法解析 --range {args.rng}")
        s_idx, e_idx = m.group(2), m.group(4)
        if s_idx > e_idx:
            raise ValueError("字母起始大于结束")
        idx_list = [c for c in string.ascii_uppercase if s_idx <= c <= e_idx]
        out_path.mkdir(parents=True, exist_ok=True)
        ok = 0
        for idx in idx_list:
            try:
                prob = fetch_problem_one(f"{args.contest}{idx}")
                p = write_problem_file(prob, out_path / f"{args.contest}{idx}.md")
                log_ok(f"{args.contest}{idx} -> {p}")
                ok += 1
            except Exception as e:
                log_err(f"{args.contest}{idx}: {e}")
            time.sleep(args.delay)
        print(f"\nDone: {ok}/{len(idx_list)}")
    elif args.contest:
        out_path.mkdir(parents=True, exist_ok=True)
        probs = fetch_contest(args.contest, max_workers=args.workers)
        for prob in probs:
            p = write_problem_file(prob, out_path / f"{prob.problem_id}.md")
            log_ok(f"{prob.problem_id} -> {p}")
        readme = out_path / "README.md"
        readme.write_text(
            f"# Codeforces Round {args.contest}\n\n"
            f"题目数: {len(probs)}\n\n"
            "| 题号 | 标题 | 难度 |\n|------|------|------|\n"
            + "\n".join(
                f"| {p.problem_id} | {p.title} | {p.constraints or '-'} |"
                for p in probs
            ),
            encoding="utf-8-sig",
        )
        log_ok(f"README -> {readme}")
    elif args.problem:
        prob = fetch_problem_one(args.problem)
        target = out_path if out_path.suffix else (out_path / f"{args.problem}.md")
        p = write_problem_file(prob, target)
        log_ok(f"{args.problem} -> {p}")
    else:
        parser.error("必须指定 --problem / --contest / --range")


if __name__ == "__main__":
    main()
