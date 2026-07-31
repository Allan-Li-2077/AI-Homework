#!/usr/bin/env python3
"""
根据省份名称，读取各地市人口并生成彩色柱状图 HTML。

用法：
  python scripts/generate_chart.py 广东
  python scripts/generate_chart.py 广东省 --out-dir ../../outputs/charts

输出：
  {out_dir}/{省份名}.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA = SKILL_DIR / "data.json"
DEFAULT_OUT = SKILL_DIR.parent.parent / "outputs" / "charts"

# 高对比、和谐的柱状配色（循环使用）
PALETTE = [
    "#2563eb", "#db2777", "#059669", "#d97706", "#7c3aed",
    "#0891b2", "#dc2626", "#65a30d", "#c026d3", "#0d9488",
    "#ea580c", "#4f46e5", "#ca8a04", "#e11d48", "#0284c7",
    "#16a34a", "#9333ea", "#b45309", "#be123c", "#0f766e",
]

SUFFIXES = ("省", "市", "壮族自治区", "回族自治区", "维吾尔自治区",
            "自治区", "特别行政区")


def normalize_province(name: str) -> str:
    name = name.strip()
    for suf in SUFFIXES:
        if name.endswith(suf) and len(name) > len(suf):
            name = name[: -len(suf)]
            break
    return name


def load_data(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}


def find_province(data: dict, query: str) -> tuple[str, dict] | None:
    key = normalize_province(query)
    if key in data:
        return key, data[key]
    # 模糊：query 包含省名或省名包含 query
    for name, cities in data.items():
        if name in query or query in name:
            return name, cities
    return None


def extract_province_from_text(text: str, data: dict) -> str | None:
    """从自然语言中提取第一个命中的省份名（长名优先）。"""
    names = sorted(data.keys(), key=len, reverse=True)
    for name in names:
        variants = [name, name + "省", name + "市"]
        if name in ("广西",):
            variants.append("广西壮族自治区")
        if name in ("新疆",):
            variants.append("新疆维吾尔自治区")
        if name in ("宁夏",):
            variants.append("宁夏回族自治区")
        if name in ("内蒙古",):
            variants.append("内蒙古自治区")
        if name in ("西藏",):
            variants.append("西藏自治区")
        for v in variants:
            if v in text:
                return name
    return None


def render_html(province: str, cities: dict[str, float], unit: str = "万人") -> str:
    # 过滤无效 / 排序
    items = [(n, float(p)) for n, p in cities.items() if float(p) > 0]
    items.sort(key=lambda x: x[1], reverse=True)
    if not items:
        raise ValueError(f"{province} 无有效人口数据")

    max_val = max(v for _, v in items)
    n = len(items)
    # 布局：竖向柱状，宽度随城市数缩放
    bar_w = 36
    gap = 14
    left = 64
    right = 40
    top = 72
    bottom = 120
    chart_h = 360
    chart_w = max(640, left + right + n * (bar_w + gap))
    svg_w = chart_w
    svg_h = top + chart_h + bottom

    bars = []
    labels = []
    values = []
    for i, (name, val) in enumerate(items):
        color = PALETTE[i % len(PALETTE)]
        h = 0 if max_val == 0 else (val / max_val) * (chart_h - 8)
        x = left + i * (bar_w + gap) + gap / 2
        y = top + chart_h - h
        bars.append(
            f'<rect class="bar" x="{x:.1f}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" '
            f'rx="6" fill="{color}" data-name="{_esc(name)}" data-value="{val:g}">'
            f'<title>{_esc(name)}：{val:g}{unit}</title></rect>'
        )
        # 数值标签
        values.append(
            f'<text x="{x + bar_w/2:.1f}" y="{y - 8:.1f}" text-anchor="middle" '
            f'class="val">{val:g}</text>'
        )
        # 城市名（倾斜）
        labels.append(
            f'<text x="{x + bar_w/2:.1f}" y="{top + chart_h + 16}" text-anchor="end" '
            f'class="label" transform="rotate(-42 {x + bar_w/2:.1f} {top + chart_h + 16})">'
            f'{_esc(name)}</text>'
        )

    # Y 轴刻度
    ticks = []
    steps = 5
    for s in range(steps + 1):
        v = max_val * s / steps
        yy = top + chart_h - (chart_h - 8) * s / steps
        ticks.append(
            f'<line x1="{left - 6}" y1="{yy:.1f}" x2="{chart_w - right}" y2="{yy:.1f}" class="grid"/>'
            f'<text x="{left - 10}" y="{yy + 4:.1f}" text-anchor="end" class="tick">{v:.0f}</text>'
        )

    total = sum(v for _, v in items)
    legend = "".join(
        f'<span class="lg"><i style="background:{PALETTE[i % len(PALETTE)]}"></i>{_esc(n)}</span>'
        for i, (n, _) in enumerate(items)
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(province)}各地市人口柱状图</title>
<style>
  :root {{
    --bg: #0b1220;
    --panel: #121a2b;
    --text: #e8eefc;
    --muted: #93a4c3;
    --line: #243047;
    --accent: #7dd3fc;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh;
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    color: var(--text);
    background:
      radial-gradient(1200px 600px at 10% -10%, #1e3a5f 0%, transparent 55%),
      radial-gradient(900px 500px at 100% 0%, #3b1d4a 0%, transparent 50%),
      var(--bg);
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 48px; }}
  header h1 {{
    margin: 0 0 8px; font-size: 28px; letter-spacing: .02em;
    background: linear-gradient(90deg, #fff, var(--accent));
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }}
  header p {{ margin: 0; color: var(--muted); font-size: 14px; }}
  .stats {{
    display: flex; flex-wrap: wrap; gap: 12px; margin: 20px 0 16px;
  }}
  .stat {{
    background: color-mix(in srgb, var(--panel) 90%, white 4%);
    border: 1px solid var(--line); border-radius: 12px; padding: 12px 16px; min-width: 140px;
  }}
  .stat b {{ display: block; font-size: 22px; }}
  .stat span {{ color: var(--muted); font-size: 12px; }}
  .panel {{
    background: var(--panel); border: 1px solid var(--line); border-radius: 16px;
    padding: 16px 12px 8px; overflow-x: auto;
    box-shadow: 0 20px 50px rgba(0,0,0,.35);
  }}
  svg {{ display: block; min-width: 100%; }}
  .grid {{ stroke: var(--line); stroke-width: 1; stroke-dasharray: 4 4; }}
  .tick {{ fill: var(--muted); font-size: 11px; }}
  .val {{ fill: #dbeafe; font-size: 11px; font-weight: 600; }}
  .label {{ fill: #cbd5e1; font-size: 12px; }}
  .bar {{ transition: opacity .15s, filter .15s; cursor: default; }}
  .bar:hover {{ filter: brightness(1.15); }}
  .axis {{ stroke: #334155; stroke-width: 1.5; }}
  .legend {{
    display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 18px;
  }}
  .lg {{ display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; }}
  .lg i {{ width: 10px; height: 10px; border-radius: 3px; display: inline-block; }}
  footer {{ margin-top: 18px; color: var(--muted); font-size: 12px; }}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>{_esc(province)} · 各地市人口柱状图</h1>
      <p>单位：{unit} · 按人口降序 · 数据来自技能包内置普查汇总（约数）</p>
    </header>
    <div class="stats">
      <div class="stat"><b>{n}</b><span>地市/区划数</span></div>
      <div class="stat"><b>{total:.0f}</b><span>合计（{unit}）</span></div>
      <div class="stat"><b>{items[0][0]}</b><span>人口最多 · {items[0][1]:g}{unit}</span></div>
    </div>
    <div class="panel">
      <svg viewBox="0 0 {svg_w} {svg_h}" width="100%" height="{svg_h}" role="img"
           aria-label="{_esc(province)}各地市人口柱状图">
        {''.join(ticks)}
        <line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" class="axis"/>
        <line x1="{left}" y1="{top + chart_h}" x2="{chart_w - right}" y2="{top + chart_h}" class="axis"/>
        {''.join(bars)}
        {''.join(values)}
        {''.join(labels)}
        <text x="{left}" y="28" fill="#94a3b8" font-size="12">人口（{unit}）</text>
      </svg>
    </div>
    <div class="legend">{legend}</div>
    <footer>文件由 province-population-chart 技能自动生成 · 柱体颜色区分各地市</footer>
  </div>
</body>
</html>
"""


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def generate(province_query: str, data_path: Path = DEFAULT_DATA, out_dir: Path = DEFAULT_OUT) -> Path:
    data = load_data(data_path)
    found = find_province(data, province_query)
    if not found:
        # 尝试从整句提取
        name = extract_province_from_text(province_query, data)
        if name:
            found = (name, data[name])
    if not found:
        known = "、".join(sorted(data.keys()))
        raise SystemExit(f"未找到省份「{province_query}」。已支持：{known}")

    province, cities = found
    # 去掉零人口异常项
    cities = {k: v for k, v in cities.items() if float(v) > 0}
    html = render_html(province, cities)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{province}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="生成省份地市人口柱状图 HTML")
    p.add_argument("province", help="省份名称，如 广东 / 广东省")
    p.add_argument("--data", type=Path, default=DEFAULT_DATA)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    path = generate(args.province, args.data, args.out_dir)
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
