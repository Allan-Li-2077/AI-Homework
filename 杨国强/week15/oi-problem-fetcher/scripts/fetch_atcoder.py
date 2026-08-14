"""AtCoder 拉取脚本：单题或整场比赛。

优化版：
- 预建索引：Sample Output 按编号直接查 O(1)，替代原来 O(n²) 嵌套循环
- BeautifulSoup import 提到模块顶层，避免每次函数调用重复 import

用法：
    python fetch_atcoder.py --task abc001_a --out ./abc001/a.md
    python fetch_atcoder.py --contest abc001 --out ./abc001/
"""
from __future__ import annotations

import argparse
import re
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
    log_err,
    log_ok,
    log_warn,
    write_problem_file,
)


ATCODER_TASK_URL = "https://atcoder.jp/contests/{contest}/tasks/{task_id}"
ATCODER_TASKS_URL = "https://atcoder.jp/contests/{contest}/tasks"


ATCODER_TASK_URL = "https://atcoder.jp/contests/{contest}/tasks/{task_id}"
ATCODER_TASKS_URL = "https://atcoder.jp/contests/{contest}/tasks"


def fetch_task(contest: str, task_id: str, lang: str = "en") -> Problem:
    """拉单题。task_id 如 'abc001_a'。

    优化：预建 dict[编号→pre文本]，O(n) 替代 O(n²) 嵌套循环。
    """
    url = f"https://atcoder.jp/contests/{contest}/tasks/{task_id}?lang={lang}"
    resp = http_get(url, retry=2)
    soup = BeautifulSoup(resp.text, "lxml")

    title_el = soup.select_one(".h2") or soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else task_id
    title = re.sub(r"^[A-Za-z]\d+\s*-\s*", "", title)

    problem_lang = soup.select_one("#task-statement") or soup.select_one(".part")
    sections = problem_lang.select(".part") if problem_lang else []
    desc_parts: list[str] = []

    # O(n) 一次遍历，同时收集所有 Input 和 Output，按编号建索引
    inputs_by_idx: dict[int, str] = {}
    outputs_by_idx: dict[int, str] = {}

    for sec in sections:
        h3 = sec.select_one("h3")
        title_txt = h3.get_text(strip=True) if h3 else ""
        pre = sec.select_one("pre")
        txt = pre.get_text("\n", strip=False).rstrip("\n") if pre else ""

        sin_m = re.search(r"Sample Input (\d+)", title_txt)
        sout_m = re.search(r"Sample Output (\d+)", title_txt)

        if sin_m:
            inputs_by_idx[int(sin_m.group(1))] = txt
        elif sout_m:
            outputs_by_idx[int(sout_m.group(1))] = txt
        else:
            md, _, _ = clean_html(str(sec), base_url=url)
            desc_parts.append(md)

    # 按编号配对（O(k)，k = max(len(inputs), len(outputs))）
    sample_nums = sorted(inputs_by_idx.keys() & outputs_by_idx.keys())
    samples = [
        Sample(input_text=inputs_by_idx[n], output_text=outputs_by_idx[n])
        for n in sample_nums
    ]

    return Problem(
        problem_id=task_id,
        platform="AtCoder",
        title=title,
        description="\n\n".join(desc_parts),
        samples=samples,
        tags=[],
        constraints="",
        source_url=url,
        has_images="<img" in resp.text,
        has_formulas="$" in "\n".join(desc_parts) or "\\(" in "\n".join(desc_parts),
    )


def list_tasks(contest: str) -> list[str]:
    """列出一场比赛的所有 task_id（O(n) 一次遍历，无嵌套循环）。"""
    url = f"https://atcoder.jp/contests/{contest}/tasks"
    resp = http_get(url, retry=2)
    soup = BeautifulSoup(resp.text, "lxml")
    ids: list[str] = []
    seen: set[str] = set()
    for a in soup.select('a[href*="/tasks/"]'):
        href = a.get("href", "")
        m = re.search(r"/tasks/([a-z0-9_]+)$", href)
        if m:
            tid = m.group(1)
            if tid.startswith(contest + "_") and tid not in seen:
                seen.add(tid)
                ids.append(tid)
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取 AtCoder 题目")
    parser.add_argument("--task", help="单题 task_id，如 abc001_a")
    parser.add_argument("--contest", help="比赛，如 abc001（拉取整场）")
    parser.add_argument("--out", required=True)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    out_path = Path(args.out)
    if args.contest and not args.task:
        out_path.mkdir(parents=True, exist_ok=True)
        task_ids = list_tasks(args.contest)
        if not task_ids:
            log_err(f"未找到 {args.contest} 的题目列表")
            sys.exit(1)
        log_ok(f"{args.contest}: {len(task_ids)} problems")
        ok = 0
        for tid in task_ids:
            try:
                prob = fetch_task(args.contest, tid)
                short = tid.split("_", 1)[1] if "_" in tid else tid
                p = write_problem_file(prob, out_path / f"{short}.md")
                log_ok(f"{tid} -> {p}")
                ok += 1
            except Exception as e:
                log_err(f"{tid}: {e}")
            time.sleep(args.delay)
        # README
        readme = out_path / "README.md"
        readme.write_text(
            f"# {args.contest}\n\n题目数: {len(task_ids)}\n",
            encoding="utf-8-sig",
        )
        log_ok(f"README -> {readme}")
        print(f"\nDone: {ok}/{len(task_ids)}")
    elif args.task:
        m = re.match(r"^([a-z]{2,3}\d{3})_([a-z])$", args.task, re.IGNORECASE)
        if not m:
            raise ValueError(f"非法 task_id: {args.task}")
        contest = m.group(1)
        prob = fetch_task(contest, args.task)
        target = out_path if out_path.suffix else (out_path / f"{args.task}.md")
        p = write_problem_file(prob, target)
        log_ok(f"{args.task} -> {p}")
    else:
        raise SystemExit("必须指定 --task 或 --contest")


if __name__ == "__main__":
    main()
