#!/usr/bin/env python3
"""Fetch ongoing ZZZ events via Bilibili Wiki SMW API and save as HTML."""
import json, os, sys, urllib.parse
from datetime import datetime
from urllib.request import urlopen, Request

API = "https://wiki.biligame.com/zzz/api.php"
QUERY = "[[分类:活动]]|?名称|?开始描述|?结束描述|?开始时间|?结束时间|?类型|?所属版本|?TAG|sort=结束时间|order=desc|limit=500"

def fetch_events():
    params = urllib.parse.urlencode({"action": "ask", "query": QUERY, "format": "json"})
    req = Request(f"{API}?{params}", headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))["query"]["results"]

def parse_date(s):
    try:
        return datetime.strptime(s.strip(), "%Y/%m/%d %H:%M")
    except (ValueError, AttributeError):
        return None

def classify(results):
    now = datetime.now()
    limited, permanent = [], []
    for v in results.values():
        p = v["printouts"]
        end_raw = p["结束时间"][0] if p.get("结束时间") else ""
        end_dt = parse_date(end_raw)
        is_perm = "永久" in (p.get("结束描述", [""])[0] if p.get("结束描述") else "")
        if not is_perm and end_dt and end_dt < now:
            continue
        start_desc = p.get("开始描述", [""])[0] if p.get("开始描述") else ""
        end_desc = p.get("结束描述", [""])[0] if p.get("结束描述") else ""
        time_range = f"{start_desc} ~ {end_desc}"
        if is_perm:
            remaining = "永久"
        elif end_dt:
            remaining = f"约{(end_dt - now).days}天"
        else:
            remaining = "至版本结束"
        evt = {
            "name": p.get("名称", [""])[0],
            "time": time_range,
            "remaining": remaining,
            "version": ", ".join(p.get("所属版本", [])),
            "tags": [t for t in p.get("TAG", []) if t != "无"],
            "types": p.get("类型", []),
        }
        (permanent if is_perm else limited).append(evt)
    return limited, permanent

CSS = """*{margin:0;padding:0;box-sizing:border-box}body{font-family:"Microsoft YaHei",sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px}
h1{text-align:center;color:#ff6b9d;margin-bottom:10px;font-size:28px}.ut{text-align:center;color:#888;margin-bottom:30px;font-size:14px}
.st{color:#c792ea;font-size:22px;margin:30px 0 15px;padding-left:10px;border-left:4px solid #c792ea}
table{width:100%;border-collapse:collapse;margin-bottom:20px;background:#16213e;border-radius:8px;overflow:hidden}
th{background:#0f3460;color:#ff6b9d;padding:12px 15px;text-align:left}td{padding:12px 15px;border-bottom:1px solid #1a1a3e}
tr:last-child td{border-bottom:none}tr:hover{background:#1a1a4e}.en{color:#82aaff;font-weight:bold}
.rm{color:#c3e88d;font-weight:bold}.pm{color:#f78c6c}.tag{display:inline-block;background:#2a2a5e;color:#89ddff;padding:2px 8px;border-radius:4px;font-size:12px;margin:2px}
.th{background:#5e2a4a;color:#ff6b9d}.src{text-align:center;color:#666;margin-top:30px;font-size:12px}"""

def tag_html(tags):
    return " ".join(f'<span class="tag th">{t}</span>' if t == "周年活动" else f'<span class="tag">{t}</span>' for t in tags)

def table_html(title, events):
    rows = ""
    for i, e in enumerate(events, 1):
        cls = "pm" if e["remaining"] == "永久" else "rm"
        rows += f'<tr><td>{i}</td><td class="en">{e["name"]}</td><td>{e["time"]}</td><td class="{cls}">{e["remaining"]}</td><td>{e["version"]}</td><td>{tag_html(e["tags"])}</td></tr>\n'
    return f'<h2 class="st">{title}</h2>\n<table><thead><tr><th>#</th><th>活动名称</th><th>活动时间</th><th>剩余时间</th><th>版本</th><th>标签</th></tr></thead><tbody>{rows}</tbody></table>'

def main():
    try:
        results = fetch_events()
    except Exception as ex:
        print(f"Error: {ex}", file=sys.stderr); sys.exit(1)
    limited, permanent = classify(results)
    today = datetime.now().strftime("%Y-%m-%d")
    body = table_html(f"限时活动（{len(limited)}个）", limited)
    body += table_html(f"永久活动（{len(permanent)}个）", permanent)
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>绝区零 - 进行中活动一览 ({today})</title><style>{CSS}</style></head><body><h1>绝区零 - 进行中活动一览</h1><p class="ut">数据获取时间：{today} | 来源：B站游戏WIKI</p>{body}<p class="src">数据来源：<a href="https://wiki.biligame.com/zzz/%E6%B4%BB%E5%8A%A8%E4%B8%80%E8%A7%88" style="color:#89ddff">绝区零WIKI - 活动一览</a></p></body></html>"""
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "events")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{today}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"OK: {len(limited)+len(permanent)} events -> {out_path}")

if __name__ == "__main__":
    main()
