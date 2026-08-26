"""英语单词 Flash Card 生成器。用法: python make_flashcard.py <data.json> [-o out.html]"""
import argparse, json, html, sys
from pathlib import Path

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{word} - Flash Card</title>
<style>
:root{{--bg:#f5f7fb;--ink:#1f2937;--muted:#6b7280;--accent:#4f46e5;--soft:#eef2ff;--border:#e5e7eb;--success:#10b981}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Roboto,sans-serif;background:var(--bg);color:var(--ink);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{width:100%;max-width:720px;background:#fff;border-radius:20px;box-shadow:0 10px 30px rgba(17,24,39,.08);overflow:hidden;transition:box-shadow .3s}}
.card:hover{{box-shadow:0 15px 40px rgba(17,24,39,.12)}}
.header{{padding:32px 36px 24px;background:linear-gradient(135deg,var(--accent) 0%,#7c3aed 100%);color:#fff}}
.word{{margin:0;font-size:44px;font-weight:700;letter-spacing:-.5px;word-break:break-word}}
.phonetic{{margin-top:8px;font-size:18px;opacity:.92;font-style:italic;cursor:pointer;user-select:none}}
.phonetic:hover{{opacity:1}}
.body{{padding:28px 36px 36px}}
.definition{{font-size:20px;line-height:1.6;padding:14px 16px;background:var(--soft);border-left:4px solid var(--accent);border-radius:8px}}
.pos{{color:var(--accent);font-weight:600;margin-right:6px}}
h2{{margin:28px 0 14px;font-size:16px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px}}
.synonyms{{display:flex;flex-wrap:wrap;gap:10px}}
.tag{{padding:6px 14px;background:var(--soft);color:var(--accent);border-radius:999px;font-size:14px;font-weight:500;cursor:default;transition:all .2s}}
.tag:hover{{background:var(--accent);color:#fff}}
.examples{{list-style:none;padding:0;margin:0}}
.examples li{{padding:14px 16px;margin-bottom:10px;background:#fafafa;border:1px solid var(--border);border-radius:10px;transition:all .2s}}
.examples li:hover{{background:#f0f0f0;border-color:var(--accent)}}
.en{{font-size:17px;line-height:1.55;color:var(--ink)}}
.zh{{margin-top:6px;font-size:14px;color:var(--muted);line-height:1.55}}
.footer{{margin-top:28px;padding-top:16px;border-top:1px dashed var(--border);font-size:12px;color:var(--muted);text-align:center}}
.error{{color:#ef4444;padding:16px;background:#fee2e2;border:1px solid #fecaca;border-radius:8px}}
</style>
</head>
<body>
<div class="card">
<div class="header"><h1 class="word">{word}</h1><div class="phonetic" title="点击复制音标">{phonetic}</div></div>
<div class="body">
<div class="definition"><span class="pos">{pos}</span>{definition}</div>
<h2>近义词</h2>
<div class="synonyms">{synonyms_html}</div>
<h2>例句</h2>
<ul class="examples">{examples_html}</ul>
<div class="footer">Flash Card · 学一个词，记一组词</div>
</div>
</div>
<script>
document.querySelector('.phonetic').addEventListener('click', function(){{
  navigator.clipboard.writeText(this.textContent);
  const orig=this.textContent;
  this.textContent='已复制 ✓';
  setTimeout(()=>{{this.textContent=orig}},1500);
}});
</script>
</body>
</html>
"""


def validate_data(data):
    """验证JSON数据完整性"""
    required = ["word", "phonetic", "pos", "definition"]
    missing = [k for k in required if k not in data or not data[k]]
    if missing:
        return False, f"缺少必需字段: {', '.join(missing)}"
    
    examples = data.get("examples", [])
    if len(examples) < 3:
        return False, f"例句不足（需3条，当前{len(examples)}条）"
    
    for i, ex in enumerate(examples[:3]):
        if "en" not in ex or "zh" not in ex:
            return False, f"例句{i+1}缺少en或zh字段"
    
    return True, None


def build(d):
    """构建HTML闪卡"""
    esc = html.escape
    syns = "\n".join(f'<span class="tag">{esc(s)}</span>' for s in d.get("synonyms", []))
    exs = (list(d.get("examples", [])[:3]) + [{}] * (3 - len(d.get("examples", []))))[:3]
    items = "\n".join(
        f'<li><div class="en">{esc(e.get("en", "") or "（待补充例句）")}</div>'
        f'<div class="zh">{esc(e.get("zh", "") or "（待补充翻译）")}</div></li>'
        for e in exs
    )
    return TEMPLATE.format(
        word=esc(d["word"]), phonetic=esc(d.get("phonetic", "")),
        pos=esc(d.get("pos", "")), definition=esc(d.get("definition", "")),
        synonyms_html=syns, examples_html=items,
    )


def main():
    p = argparse.ArgumentParser(description="生成英语单词 Flash Card HTML")
    p.add_argument("data", help="输入 JSON 文件路径")
    p.add_argument("-o", "--output", help="输出路径（默认当前目录 <word>.html）")
    p.add_argument("--check", action="store_true", help="仅检查数据有效性，不生成HTML")
    
    try:
        a = p.parse_args()
        d = json.load(open(a.data, encoding="utf-8"))
        
        valid, err = validate_data(d)
        if not valid:
            print(f"❌ 数据验证失败: {err}", file=sys.stderr)
            return 1
        
        if a.check:
            print(f"✓ 数据有效 ({d['word']})")
            return 0
        
        out = Path(a.output) if a.output else Path.cwd() / f"{d['word']}.html"
        out.write_text(build(d), encoding="utf-8")
        print(f"✓ 已生成: {out}")
        return 0
    except FileNotFoundError:
        print(f"❌ 文件不存在: {a.data}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"❌ JSON 格式错误: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ 生成失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
