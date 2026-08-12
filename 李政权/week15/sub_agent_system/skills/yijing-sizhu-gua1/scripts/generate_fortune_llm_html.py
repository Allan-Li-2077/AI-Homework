#!/usr/bin/env python3
"""
yijing-sizhu-gua1：起卦逻辑复用 yijing-sizhu-gua，完整 HTML 由 LLM 生成。

用法：
  python generate_fortune_llm_html.py "@yijing-sizhu-gua1 算命：李明，男，1990-08-15，辰时"
  python generate_fortune_llm_html.py --name 李明 --gender 男 --birth 1990-08-15 --shichen 辰
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

SKILL_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SKILL_DIR.parent.parent
DEFAULT_OUT = PROJECT_ROOT / "outputs" / "fortune1"
SIBLING_SCRIPTS = PROJECT_ROOT / "skills" / "yijing-sizhu-gua" / "scripts"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SIBLING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SIBLING_SCRIPTS))

from generate_fortune import (  # noqa: E402
    brief_for_chat,
    cast_hexagram,
    compose_reading,
    normalize_shichen,
    parse_birth_date,
    parse_fortune_query,
    render_html,
    write_metrics,
)

SKILL_NAME = "yijing-sizhu-gua1"


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:html)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    if text.lower().startswith("```"):
        text = re.sub(r"^```(?:html)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _looks_like_html(doc: str) -> bool:
    low = doc.lower()
    return "<html" in low and ("<!doctype" in low or "<head" in low or "<body" in low)


def _finalize_html(doc: str) -> str:
    """补全被截断的收尾标签，尽量保住 LLM 正文。"""
    low = doc.lower()
    if "<html" in low and "</html>" not in low:
        if "</body>" not in low:
            if "<body" in low:
                doc += "\n</body>"
            else:
                doc += "\n</body>"
        doc += "\n</html>"
    return doc


def llm_generate_html(
    name: str,
    gender: str,
    birth: str,
    gua: dict,
    generated_at: str,
) -> tuple[str, dict, bool]:
    """
    返回 (html, usage, used_fallback)。
    HTML 正文由 LLM 生成；失败则回落 Python 模板页。
    """
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "model": ""}
    try:
        from src.llm_config import get_chat_client, current_model_info
        info = current_model_info()
        usage["model"] = info.get("model", "")
        client, model = get_chat_client()
    except Exception as e:
        reading = compose_reading(name, gender, birth, gua)
        reading += f"\n\n（LLM HTML 不可用，已回落模板：{e}）"
        metrics_stub = {
            "elapsed_s": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "model": "",
        }
        return (
            render_html(name, gender, birth, gua, reading, metrics_stub, generated_at),
            usage,
            True,
        )

    system = (
        "你是前端与易经顾问。根据卦象信息输出【完整可运行的单文件 HTML】。"
        "要求：1) 必须以 <!DOCTYPE html> 开头，含 html/head/body；"
        "2) 界面简洁，八卦图样作背景（可用内联 SVG，八个卦符环绕）；"
        "3) 无外网 CDN、无外部图片；"
        "4) 正文含：信息确认、本卦变卦、命局提要、性格与课题、近/中/远期走势、开运建议、免责声明；"
        "5) 解读约 600～1000 字，CSS 精简，语气沉稳鼓励，禁止恐吓与绝对吉凶；"
        "6) 只输出 HTML 源码，不要 Markdown 解释，不要代码块围栏；必须完整闭合 html/body。"
    )
    user = (
        f"姓名：{name}\n性别：{gender}\n出生：{birth} {gua['shichen']}时\n"
        f"生成时间：{generated_at}\n"
        f"推算：{json.dumps(gua['calc'], ensure_ascii=False)}\n"
        f"上卦：{gua['upper']['name']}{gua['upper']['symbol']}（{gua['upper']['image']}·{gua['upper']['element']}）\n"
        f"下卦：{gua['lower']['name']}{gua['lower']['symbol']}（{gua['lower']['image']}·{gua['lower']['element']}）\n"
        f"本卦：{gua['ben_gua']['name']}（{gua['ben_gua']['keyword']}）{gua['ben_gua']['display']}\n"
        f"动爻：{gua['moving_yao_name']}\n"
        f"变卦：{gua['bian_gua']['name']}（{gua['bian_gua']['keyword']}）{gua['bian_gua']['display']}\n"
        "请直接输出完整 HTML。"
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.6,
        max_tokens=6000,
        stream=False,
    )
    raw = (resp.choices[0].message.content or "").strip()
    u = getattr(resp, "usage", None)
    if u is not None:
        usage["prompt_tokens"] = int(getattr(u, "prompt_tokens", 0) or 0)
        usage["completion_tokens"] = int(getattr(u, "completion_tokens", 0) or 0)
        usage["total_tokens"] = int(getattr(u, "total_tokens", 0) or 0)

    html_doc = _finalize_html(_strip_code_fence(raw))
    if not _looks_like_html(html_doc):
        reading = compose_reading(name, gender, birth, gua)
        reading += "\n\n（模型未返回合法 HTML，已回落模板页）"
        metrics_stub = {
            "elapsed_s": 0,
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "total_tokens": usage["total_tokens"],
            "model": usage.get("model") or "",
        }
        return (
            render_html(name, gender, birth, gua, reading, metrics_stub, generated_at),
            usage,
            True,
        )

    # 在页脚注入指标占位，落盘前再替换
    if "</body>" in html_doc.lower():
        # 大小写不敏感替换结尾
        html_doc = re.sub(
            r"</body>",
            '<footer id="skill-metrics" style="text-align:center;font-size:12px;'
            'color:#666;margin:2rem 0;font-family:monospace">'
            "<!--METRICS--></footer>\n</body>",
            html_doc,
            count=1,
            flags=re.IGNORECASE,
        )
    return html_doc, usage, False


def _inject_metrics(html_doc: str, metrics: dict) -> str:
    block = (
        f"skill={SKILL_NAME} | mode=llm_html"
        f" | elapsed_s={metrics.get('elapsed_s')}"
        f" | tokens={metrics.get('total_tokens')}"
        f" (p{metrics.get('prompt_tokens')}+c{metrics.get('completion_tokens')})"
        f" | model={metrics.get('model') or '-'}"
        f" | fallback={metrics.get('fallback')}"
    )
    if "<!--METRICS-->" in html_doc:
        return html_doc.replace("<!--METRICS-->", block)
    return html_doc


def run(
    name: str,
    gender: str,
    birth: str,
    shichen: str,
    out_dir: Path,
) -> dict:
    t0 = time.perf_counter()
    y, m, d = (int(x) for x in birth.split("-"))
    gua = cast_hexagram(y, m, d, shichen)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", name) or "user"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{safe_name}_{stamp}.html"

    html_doc, usage, fallback = llm_generate_html(
        name, gender, birth, gua, generated_at
    )

    metrics = {
        "skill": SKILL_NAME,
        "mode": "llm_html",
        "fallback": fallback,
        "input": {
            "name": name,
            "gender": gender,
            "birth": birth,
            "shichen": shichen,
        },
        "ben_gua": gua["ben_gua"]["name"],
        "bian_gua": gua["bian_gua"]["name"],
        "elapsed_s": round(time.perf_counter() - t0, 4),
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "total_tokens": usage["total_tokens"],
        "model": usage.get("model") or "",
        "output_path": str(out_path.resolve()),
        "generated_at": generated_at,
    }
    html_doc = _inject_metrics(html_doc, metrics)
    out_path.write_text(html_doc, encoding="utf-8")
    metrics["elapsed_s"] = round(time.perf_counter() - t0, 4)
    metrics["output_path"] = str(out_path.resolve())
    write_metrics(out_dir, metrics)

    brief = brief_for_chat(name, gua, str(out_path), metrics)
    brief = brief.replace("/fortune/", "/fortune1/")
    return {
        "ok": True,
        "output_path": str(out_path.resolve()),
        "metrics": metrics,
        "ben_gua": gua["ben_gua"]["name"],
        "bian_gua": gua["bian_gua"]["name"],
        "brief": brief,
        "summary": {
            "name": name,
            "ben_gua": gua["ben_gua"]["name"],
            "bian_gua": gua["bian_gua"]["name"],
            "moving_yao": gua["moving_yao_name"],
            "elapsed_s": metrics["elapsed_s"],
            "total_tokens": metrics["total_tokens"],
            "mode": "llm_html",
            "fallback": fallback,
            "brief": brief,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="四柱起卦 · LLM 生成 HTML")
    parser.add_argument("text", nargs="?", help="自然语言输入")
    parser.add_argument("--name", default="")
    parser.add_argument("--gender", default="")
    parser.add_argument("--birth", default="")
    parser.add_argument("--shichen", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    if args.text:
        # 去掉显式 skill 标记，避免干扰姓名解析
        cleaned = re.sub(
            r"(?:/skill\s+|@skill\s+|@)yijing-sizhu-gua1\b",
            " ",
            args.text,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if "算命" not in cleaned and "排盘" not in cleaned:
            cleaned = "算命：" + cleaned
        info = parse_fortune_query(cleaned)
    else:
        info = {
            "name": args.name or None,
            "gender": args.gender or None,
            "birth": args.birth or None,
            "shichen": normalize_shichen(args.shichen) if args.shichen else None,
            "missing": [],
        }

    if args.name:
        info["name"] = args.name
    if args.gender:
        info["gender"] = args.gender
    if args.birth:
        bt = parse_birth_date(args.birth) or parse_birth_date(args.birth.replace("-", ""))
        info["birth"] = (
            f"{bt[0]:04d}-{bt[1]:02d}-{bt[2]:02d}" if bt else args.birth
        )
    if args.shichen:
        info["shichen"] = normalize_shichen(args.shichen) or args.shichen.replace("时", "")

    info["missing"] = [
        label
        for field, label in (
            ("name", "姓名"),
            ("gender", "性别"),
            ("birth", "出生年月日"),
            ("shichen", "时辰"),
        )
        if not info.get(field)
    ]
    if info["missing"]:
        print(json.dumps({
            "ok": False,
            "error": "信息不完整，缺少：" + "、".join(info["missing"]),
            "missing": info["missing"],
        }, ensure_ascii=False))
        return 2

    try:
        result = run(
            name=info["name"],
            gender=info["gender"],
            birth=info["birth"],
            shichen=info["shichen"],
            out_dir=Path(args.out_dir),
        )
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
