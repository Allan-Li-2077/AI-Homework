"""
英语单词记忆卡 (Word Memo) 生成器
=================================
为一个英语单词生成一张静态 HTML 记忆页，聚焦"以词根/派生/联想"帮助记忆，包含：
  - 单词、音标、词性、释义
  - 词根词缀分析（root_analysis）：拆解构词，解释含义来源
  - 派生词表格（derivatives）：同根/变形词 + 词性 + 释义
  - 联想记忆（mnemonics）：谐音/画面/故事等记忆钩子
  - 关联词网络（associations）：近义/反义/同主题词
  - 例句（examples）：中英对照

用法:
    # 方式一（推荐，免写 JSON）：字段直接用命令行参数传入
    python make_memo.py --word abandon --phonetic "/əˈbændən/" --pos "v. / n." \\
        --definition "放弃，抛弃" --root "a-(向)+bandon(控制权)→交出→放弃" \\
        --deriv "abandoned|adj.|被遗弃的" --deriv "abandonment|n.|放弃" \\
        --mnemonic "谐音'额不能都'" --syn desert --syn forsake \\
        --example "They abandoned the ship.||他们弃船了。" \\
        -o output/abandon.html

    # 方式二（向后兼容）：从 JSON 文件读取
    python make_memo.py <data.json>                  # 输出到项目根 output/<word>.html
    python make_memo.py <data.json> -o output.html   # 指定输出路径

字段直传约定（避免 JSON-in-JSON 转义）：
    --deriv   "word|pos|meaning"   可重复，用竖线分隔三段
    --mnemonic "文本"               可重复
    --syn / --ant / --theme "词"    可重复（近义/反义/同主题）
    --example "英文||中文"           可重复，用双竖线分隔中英

JSON 数据格式（方式二）:
{
  "word": "abandon",
  "phonetic": "/əˈbændən/",
  "pos": "v. / n.",
  "definition": "放弃，抛弃；放纵",
  "root_analysis": "a-(向) + bandon(控制权) → 交出控制权 → 放弃",
  "derivatives": [
    {"word": "abandoned", "pos": "adj.", "meaning": "被遗弃的；放荡的"},
    {"word": "abandonment", "pos": "n.", "meaning": "放弃；遗弃"}
  ],
  "mnemonics": [
    "谐音'额，不能都'——都放弃了才说这句。",
    "画面：一个人把行李全扔在月台上转身离开。"
  ],
  "associations": {
    "synonyms": ["desert", "forsake", "give up"],
    "antonyms": ["keep", "retain", "maintain"],
    "theme": ["quit", "discard", "relinquish"]
  },
  "examples": [
    {"en": "...", "zh": "..."}
  ]
}
所有字段除 word 外均可缺省；缺省项对应版块自动隐藏。
"""
import argparse
import html
import json
import re
from pathlib import Path


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{word} - Word Memo</title>
<style>
  :root {{
    --bg: #f4f6fb;
    --card: #ffffff;
    --ink: #1f2937;
    --muted: #6b7280;
    --accent: #0d9488;
    --accent2: #6366f1;
    --accent-soft: #e6fffb;
    --border: #e5e7eb;
    --shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Microsoft YaHei", Roboto, sans-serif;
    background: var(--bg);
    color: var(--ink);
    min-height: 100vh;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 32px 20px;
  }}
  .card {{
    width: 100%;
    max-width: 760px;
    background: var(--card);
    border-radius: 20px;
    box-shadow: var(--shadow);
    overflow: hidden;
  }}
  .header {{
    padding: 32px 36px 26px;
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent2) 100%);
    color: #fff;
  }}
  .word {{ margin: 0; font-size: 46px; font-weight: 700; letter-spacing: -0.5px; }}
  .phonetic {{ margin-top: 8px; font-size: 18px; opacity: 0.92; font-style: italic; }}
  .body {{ padding: 28px 36px 36px; }}
  .definition {{
    font-size: 20px; line-height: 1.6; padding: 14px 16px;
    background: var(--accent-soft); border-left: 4px solid var(--accent);
    border-radius: 8px;
  }}
  .definition .pos {{ color: var(--accent); font-weight: 600; margin-right: 6px; }}
  h2 {{
    margin: 30px 0 14px; font-size: 15px; font-weight: 600; color: var(--muted);
    text-transform: uppercase; letter-spacing: 1px;
  }}
  .root {{
    padding: 14px 16px; background: #fffbea; border: 1px dashed #f0c000;
    border-radius: 10px; font-size: 16px; line-height: 1.6;
  }}
  table.deriv {{ width: 100%; border-collapse: collapse; font-size: 15px; }}
  table.deriv th, table.deriv td {{
    text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border);
  }}
  table.deriv th {{ color: var(--muted); font-weight: 600; font-size: 13px; }}
  table.deriv td.w {{ font-weight: 600; color: var(--accent2); }}
  table.deriv td.p {{ color: var(--accent); white-space: nowrap; }}
  .mnemonics {{ list-style: none; padding: 0; margin: 0; }}
  .mnemonics li {{
    padding: 12px 16px; margin-bottom: 10px; background: #fdf2f8;
    border: 1px solid #fbcfe8; border-radius: 10px; line-height: 1.6;
  }}
  .assoc-group {{ margin-bottom: 12px; }}
  .assoc-label {{ font-size: 13px; color: var(--muted); margin-bottom: 6px; }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .tags .tag {{
    padding: 5px 12px; border-radius: 999px; font-size: 14px; font-weight: 500;
    background: var(--accent-soft); color: var(--accent);
  }}
  .tags .tag.ant {{ background: #fee2e2; color: #dc2626; }}
  .tags .tag.theme {{ background: #eef2ff; color: var(--accent2); }}
  .examples {{ list-style: none; padding: 0; margin: 0; }}
  .examples li {{
    padding: 14px 16px; margin-bottom: 10px; background: #fafafa;
    border: 1px solid var(--border); border-radius: 10px;
  }}
  .examples .en {{ font-size: 17px; line-height: 1.55; }}
  .examples .zh {{ margin-top: 6px; font-size: 14px; color: var(--muted); line-height: 1.55; }}
  .footer {{
    margin-top: 30px; padding-top: 16px; border-top: 1px dashed var(--border);
    font-size: 12px; color: var(--muted); text-align: center;
  }}
</style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h1 class="word">{word}</h1>
      <div class="phonetic">{phonetic}</div>
    </div>
    <div class="body">
      <div class="definition">
        <span class="pos">{pos}</span>{definition}
      </div>
{sections}
      <div class="footer">Word Memo · 拆词根 · 记派生 · 巧联想</div>
    </div>
  </div>
</body>
</html>
"""


def _section(title, inner):
    """包一个带标题的版块；inner 为空则返回空串（该版块隐藏）。"""
    if not inner:
        return ""
    return f"\n      <h2>{html.escape(title)}</h2>\n      {inner}\n"


def render_root(root_analysis):
    if not root_analysis:
        return ""
    return _section("词根词缀", f'<div class="root">{html.escape(root_analysis)}</div>')


def render_derivatives(derivatives):
    if not derivatives:
        return ""
    rows = []
    for d in derivatives:
        w = html.escape(d.get("word", ""))
        p = html.escape(d.get("pos", ""))
        m = html.escape(d.get("meaning", ""))
        rows.append(
            f'<tr><td class="w">{w}</td><td class="p">{p}</td><td>{m}</td></tr>'
        )
    table = (
        '<table class="deriv"><thead><tr>'
        "<th>派生词</th><th>词性</th><th>释义</th>"
        "</tr></thead><tbody>\n        "
        + "\n        ".join(rows)
        + "\n      </tbody></table>"
    )
    return _section("派生词", table)


def render_mnemonics(mnemonics):
    if not mnemonics:
        return ""
    items = "\n        ".join(
        f"<li>{html.escape(m)}</li>" for m in mnemonics
    )
    return _section("联想记忆", f'<ul class="mnemonics">\n        {items}\n      </ul>')


def _tag_group(label, words, cls=""):
    if not words:
        return ""
    tags = "".join(
        f'<span class="tag {cls}">{html.escape(w)}</span>' for w in words
    )
    return (
        f'<div class="assoc-group"><div class="assoc-label">{html.escape(label)}</div>'
        f'<div class="tags">{tags}</div></div>'
    )


def render_associations(assoc):
    if not assoc:
        return ""
    inner = (
        _tag_group("近义词", assoc.get("synonyms", []))
        + _tag_group("反义词", assoc.get("antonyms", []), "ant")
        + _tag_group("同主题", assoc.get("theme", []), "theme")
    )
    return _section("关联词", inner) if inner else ""


def render_examples(examples):
    if not examples:
        return ""
    items = []
    for ex in examples:
        en = html.escape(ex.get("en", ""))
        zh = html.escape(ex.get("zh", ""))
        items.append(f'<li><div class="en">{en}</div><div class="zh">{zh}</div></li>')
    lst = "\n        ".join(items)
    return _section("例句", f'<ul class="examples">\n        {lst}\n      </ul>')


# 版面各版块的规范名称与默认展示顺序（deriv/mnemonic 为核心，永不可关）
DEFAULT_SECTION_ORDER = ["root", "deriv", "mnemonic", "association", "example"]
_CORE_SECTIONS = ("deriv", "mnemonic")

# 匹配 // 行注释与 /* */ 块注释，但保护字符串字面量内的同形字符（如 URL 里的 //）。
_JSONC_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"'      # 双引号字符串（含转义），整体跳过不动
    r"|//[^\n]*"              # 行注释
    r"|/\*.*?\*/",           # 块注释
    re.DOTALL,
)


def _loads_jsonc(text):
    """容错解析：先按标准 JSON，失败再剔除 // 与 /* */ 注释后重试。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        stripped = _JSONC_TOKEN.sub(
            lambda m: m.group(0) if m.group(0).startswith('"') else "", text
        )
        return json.loads(stripped)


def _load_config(config_path):
    """读取渲染配置；缺失或损坏时返回空 dict（走默认顺序、全部版块可见）。"""
    path = Path(config_path) if config_path else Path(__file__).resolve().parent / "config.json"
    try:
        cfg = _loads_jsonc(path.read_text(encoding="utf-8"))
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def build_html(data, config=None):
    config = config or {}
    order = config.get("section_order") or DEFAULT_SECTION_ORDER
    optional = config.get("optional_sections") or {}

    # 每个版块先各自渲染成 HTML 片段（空数据自动返回空串→隐藏）
    rendered = {
        "root": render_root(data.get("root_analysis")),
        "deriv": render_derivatives(data.get("derivatives", [])),
        "mnemonic": render_mnemonics(data.get("mnemonics", [])),
        "association": render_associations(data.get("associations", {})),
        "example": render_examples(data.get("examples", [])),
    }

    parts = []
    seen = set()
    # 先按 config 的顺序拼；未知名忽略，重复名去重
    for name in order:
        if name in rendered and name not in seen:
            seen.add(name)
            # 可选版块被显式关闭则跳过；核心版块无视开关
            if name not in _CORE_SECTIONS and optional.get(name) is False:
                continue
            parts.append(rendered[name])
    # config 顺序里漏掉的版块（如新增版块），按默认顺序补在后面，避免内容丢失
    for name in DEFAULT_SECTION_ORDER:
        if name not in seen:
            if name not in _CORE_SECTIONS and optional.get(name) is False:
                continue
            parts.append(rendered[name])

    return TEMPLATE.format(
        word=html.escape(data["word"]),
        phonetic=html.escape(data.get("phonetic", "")),
        pos=html.escape(data.get("pos", "")),
        definition=html.escape(data.get("definition", "")),
        sections="".join(parts),
    )


def _parse_deriv(items):
    """把 'word|pos|meaning' 列表解析为派生词对象列表。"""
    out = []
    for raw in items or []:
        parts = [s.strip() for s in raw.split("|")]
        parts += [""] * (3 - len(parts))  # 不足补空
        out.append({"word": parts[0], "pos": parts[1], "meaning": parts[2]})
    return out


def _parse_example(items):
    """把 '英文||中文' 列表解析为例句对象列表。"""
    out = []
    for raw in items or []:
        if "||" in raw:
            en, zh = raw.split("||", 1)
        else:
            en, zh = raw, ""
        out.append({"en": en.strip(), "zh": zh.strip()})
    return out


def data_from_args(args):
    """把命令行字段参数组装成与 JSON 等价的 data dict。"""
    data = {"word": args.word}
    if args.phonetic:
        data["phonetic"] = args.phonetic
    if args.pos:
        data["pos"] = args.pos
    if args.definition:
        data["definition"] = args.definition
    if args.root:
        data["root_analysis"] = args.root
    if args.deriv:
        data["derivatives"] = _parse_deriv(args.deriv)
    if args.mnemonic:
        data["mnemonics"] = list(args.mnemonic)
    assoc = {}
    if args.syn:
        assoc["synonyms"] = list(args.syn)
    if args.ant:
        assoc["antonyms"] = list(args.ant)
    if args.theme:
        assoc["theme"] = list(args.theme)
    if assoc:
        data["associations"] = assoc
    if args.example:
        data["examples"] = _parse_example(args.example)
    return data


def main():
    parser = argparse.ArgumentParser(description="生成英语单词记忆卡 Word Memo HTML")
    # 方式二：JSON 文件（位置参数，可选）
    parser.add_argument("data", nargs="?", help="JSON 数据文件路径（不传则用 --word 等字段直传）")
    # 方式一：字段直传（推荐，免写 JSON，避免转义问题）
    parser.add_argument("--word", help="单词（用字段直传时必填）")
    parser.add_argument("--phonetic", help="音标，如 /əˈbændən/")
    parser.add_argument("--pos", help="词性，如 'v. / n.'")
    parser.add_argument("--definition", help="中文释义")
    parser.add_argument("--root", help="词根词缀拆解（一句话）")
    parser.add_argument("--deriv", action="append",
                        help="派生词 'word|pos|meaning'，可重复")
    parser.add_argument("--mnemonic", action="append", help="联想记忆一条，可重复")
    parser.add_argument("--syn", action="append", help="近义词，可重复")
    parser.add_argument("--ant", action="append", help="反义词，可重复")
    parser.add_argument("--theme", action="append", help="同主题词，可重复")
    parser.add_argument("--example", action="append",
                        help="例句 '英文||中文'，可重复")
    parser.add_argument("-o", "--output",
                        help="输出 HTML 路径（默认项目根 output/<word>.html）")
    parser.add_argument("--config",
                        help="渲染配置 JSON 路径（默认脚本同目录 config.json）")
    args = parser.parse_args()

    if args.data:
        with open(args.data, "r", encoding="utf-8") as f:
            data = json.load(f)
    elif args.word:
        data = data_from_args(args)
    else:
        parser.error("必须提供 JSON 文件路径，或用 --word 等字段直传")

    config = _load_config(args.config)
    out_path = (
        Path(args.output) if args.output
        else Path(__file__).resolve().parents[3] / "output" / f"{data['word']}.html"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_html(data, config), encoding="utf-8")
    print(f"已生成: {out_path}")


if __name__ == "__main__":
    main()
