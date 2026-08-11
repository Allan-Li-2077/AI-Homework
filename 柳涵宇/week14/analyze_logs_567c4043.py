#!/usr/bin/env python3
"""Streaming log analyzer: nginx/apache access logs, JSON lines, plain app logs.

Prints a single JSON report to stdout. O(1) memory in file size (bounded counters).
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone

NGINX_RE = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] '
    r'"(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" '
    r'(?P<status>\d{3}) (?P<size>\d+|-)'
)
APP_RE = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)\S*\s+'
    r'(?P<level>TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERR(?:OR)?|CRIT(?:ICAL)?|FATAL|ALERT|EMERG)\b'
)
LEVELS = {"TRACE", "DEBUG", "INFO", "NOTICE", "WARN", "WARNING", "ERROR", "ERR",
          "CRITICAL", "CRIT", "FATAL", "ALERT", "EMERG"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
TOP_CAP = 50_000  # bound counters for pathological cardinality


def detect_format(lines):
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("{") and ln.endswith("}"):
            try:
                json.loads(ln)
                return "json"
            except ValueError:
                pass
        if NGINX_RE.match(ln):
            return "nginx"
        if APP_RE.match(ln):
            return "app"
    return "app"


def parse_iso(ts):
    ts = ts.replace(" ", "T", 1)
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def pick(d, names):
    for n in names:
        if n in d:
            return d[n]
    return None


def strip_query(path):
    return path.split("?", 1)[0] if "?" in path else path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", help="log file path, or '-' for stdin")
    ap.add_argument("--format", default="auto", choices=["auto", "nginx", "apache", "json", "app"])
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--grep", help="only count lines containing this substring")
    ap.add_argument("--limit", type=int, default=0, help="stop after N lines (0 = all)")
    args = ap.parse_args()

    opener = (lambda: sys.stdin) if args.file == "-" else (
        lambda: open(args.file, encoding="utf-8", errors="replace"))

    fmt = args.format
    if fmt == "apache":
        fmt = "nginx"  # same pattern matches both

    status_counts, path_counts, ip_counts = Counter(), Counter(), Counter()
    level_counts, minute_counts = Counter(), Counter()
    total = parsed = skipped = 0
    size_sum = size_n = 0
    bad_samples = []
    first_ts = last_ts = None

    with opener() as f:
        probe = []
        if fmt == "auto":
            probe = [next(f, "") for _ in range(100)]
            fmt = detect_format([l for l in probe if l.strip()])
            it = iter(list(probe) + list(f))
        else:
            it = f
        for line in it:
            total += 1
            if args.limit and total > args.limit:
                break
            if args.grep and args.grep not in line:
                skipped += 1
                continue
            d = None
            minute = norm = None
            if fmt == "nginx":
                # fast path: string slicing instead of datetime parsing
                m = NGINX_RE.match(line)
                if m:
                    ip, ts, _method, path, status, size = m.groups()
                    status_counts[status] += 1
                    p = path.split("?", 1)[0]
                    if len(path_counts) < TOP_CAP:
                        path_counts[p] += 1
                    if len(ip_counts) < TOP_CAP:
                        ip_counts[ip] += 1
                    if size.isdigit():
                        size_sum += int(size)
                        size_n += 1
                    if len(ts) >= 20:
                        mo = MONTHS.get(ts[3:6])
                        if mo:
                            minute = f"{ts[7:11]}-{mo:02d}-{ts[0:2]} {ts[12:17]}"
                            norm = f"{minute}:{ts[18:20]}"
                            if len(minute_counts) < TOP_CAP:
                                minute_counts[minute] += 1
                    if norm:
                        if first_ts is None or norm < first_ts:
                            first_ts = norm
                        if last_ts is None or norm > last_ts:
                            last_ts = norm
                    parsed += 1
                    continue
            elif fmt == "json":
                s = line.strip()
                if s.startswith("{"):
                    try:
                        obj = json.loads(s)
                        ts = str(pick(obj, ["timestamp", "@timestamp", "time", "ts"]) or "")
                        lvl = str(pick(obj, ["level", "severity", "loglevel", "lvl"]) or "").upper()
                        size = pick(obj, ["bytes", "size", "response_size"])
                        d = {"status": str(pick(obj, ["status", "status_code", "code"]) or ""),
                             "path": str(pick(obj, ["path", "url", "uri", "endpoint"]) or ""),
                             "ip": str(pick(obj, ["ip", "client_ip", "remote_addr", "source_ip"]) or ""),
                             "size": str(size) if size is not None else "-",
                             "level": lvl if lvl in LEVELS else "",
                             "dt": parse_iso(ts)}
                    except ValueError:
                        pass
            else:  # app
                m = APP_RE.match(line)
                if m:
                    lvl = m.group("level")
                    lvl = "ERROR" if lvl in ("ERR",) else lvl
                    lvl = "WARN" if lvl == "WARNING" else lvl
                    lvl = "CRITICAL" if lvl == "CRIT" else lvl
                    d = {"level": lvl, "dt": parse_iso(m.group("ts"))}
                elif re.search(r"\b(ERROR|WARN|FATAL|CRITICAL)\b", line):
                    lvl = re.search(r"\b(ERROR|WARN|FATAL|CRITICAL)\b", line).group(1)
                    d = {"level": lvl, "dt": None}

            if d is None:
                if len(bad_samples) < 3:
                    bad_samples.append(line.strip()[:200])
                continue

            parsed += 1
            if d.get("status"):
                status_counts[d["status"]] += 1
            if d.get("level"):
                level_counts[d["level"]] += 1
            if d.get("path"):
                p = strip_query(d["path"])
                if len(path_counts) < TOP_CAP:
                    path_counts[p] += 1
            if d.get("ip") and len(ip_counts) < TOP_CAP:
                ip_counts[d["ip"]] += 1
            if d.get("size") not in (None, "-", ""):
                try:
                    size_sum += int(d["size"]); size_n += 1
                except ValueError:
                    pass
            dt = d.get("dt")
            if dt:
                minute = f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d} {dt.hour:02d}:{dt.minute:02d}"
                norm = f"{minute}:{dt.second:02d}"
                if len(minute_counts) < TOP_CAP:
                    minute_counts[minute] += 1
            if norm:
                if first_ts is None or norm < first_ts:
                    first_ts = norm
                if last_ts is None or norm > last_ts:
                    last_ts = norm

    five_xx = sum(c for s, c in status_counts.items() if s.startswith("5"))
    four_xx = sum(c for s, c in status_counts.items() if s.startswith("4"))
    error_levels = sum(c for l, c in level_counts.items()
                       if l in ("ERROR", "FATAL", "CRITICAL", "ALERT", "EMERG"))
    report = {
        "file": args.file,
        "format": fmt,
        "lines_total": total,
        "lines_parsed": parsed,
        "parse_errors": parsed == 0 and total > 0,
        "parse_error_rate": round((total - parsed - skipped) / total, 4) if total else 0.0,
        "skipped_by_grep": skipped,
        "time_range": [first_ts.replace(" ", "T") if first_ts else None,
                       last_ts.replace(" ", "T") if last_ts else None],
        "status_counts": dict(sorted(status_counts.items())),
        "level_counts": dict(sorted(level_counts.items(), key=lambda x: -x[1])),
        "http_error_rate": round((four_xx + five_xx) / parsed, 4) if parsed and status_counts else None,
        "5xx_rate": round(five_xx / parsed, 4) if parsed and status_counts else None,
        "app_error_rate": round(error_levels / parsed, 4) if parsed and level_counts else None,
        "top_paths": path_counts.most_common(args.top),
        "top_ips": ip_counts.most_common(args.top),
        "peak_minutes": minute_counts.most_common(min(args.top, 5)),
        "avg_response_bytes": round(size_sum / size_n, 1) if size_n else None,
        "sample_unparsed": bad_samples,
    }
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
