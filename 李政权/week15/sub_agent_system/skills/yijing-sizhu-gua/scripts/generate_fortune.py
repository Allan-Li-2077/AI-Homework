#!/usr/bin/env python3
"""
四柱数字起卦 → LLM 解读 → 动态生成八卦背景 HTML，并记录用时与 Token。

用法：
  python generate_fortune.py "算命：李明，男，1990-08-15，辰时"
  python generate_fortune.py --name 李明 --gender 男 --birth 1990-08-15 --shichen 辰

输出：
  outputs/fortune/{姓名}_{时间戳}.html
  outputs/fortune/metrics_latest.json
  stdout 最后一行：JSON 结果
"""

from __future__ import annotations

import argparse
import html
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
DEFAULT_OUT = PROJECT_ROOT / "outputs" / "fortune"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 余数 1~8 → 八卦
TRIGRAMS = {
    1: ("乾", "☰", "天", "金"),
    2: ("兑", "☱", "泽", "金"),
    3: ("离", "☲", "火", "火"),
    4: ("震", "☳", "雷", "木"),
    5: ("巽", "☴", "风", "木"),
    6: ("坎", "☵", "水", "水"),
    7: ("艮", "☶", "山", "土"),
    8: ("坤", "☷", "地", "土"),
}

SHICHEN = {
    "子": 1, "丑": 2, "寅": 3, "卯": 4, "辰": 5, "巳": 6,
    "午": 7, "未": 8, "申": 9, "酉": 10, "戌": 11, "亥": 12,
}

# 时辰 ↔ 钟点（起始小时）
HOUR_TO_SHICHEN = [
    (23, "子"), (1, "丑"), (3, "寅"), (5, "卯"), (7, "辰"), (9, "巳"),
    (11, "午"), (13, "未"), (15, "申"), (17, "酉"), (19, "戌"), (21, "亥"),
]

# 上卦名, 下卦名 → (卦名, 关键词)
HEXAGRAMS: dict[tuple[str, str], tuple[str, str]] = {
    ("乾", "乾"): ("乾为天", "刚健进取"),
    ("乾", "坤"): ("天地否", "闭塞待时"),
    ("乾", "震"): ("天雷无妄", "顺其自然"),
    ("乾", "坎"): ("天水讼", "争讼宜解"),
    ("乾", "艮"): ("天山遁", "知退保身"),
    ("乾", "巽"): ("天风姤", "邂逅机缘"),
    ("乾", "离"): ("天火同人", "同心协力"),
    ("乾", "兑"): ("天泽履", "慎行守礼"),
    ("坤", "乾"): ("地天泰", "通达安和"),
    ("坤", "坤"): ("坤为地", "厚德载物"),
    ("坤", "震"): ("地雷复", "回复生机"),
    ("坤", "坎"): ("地水师", "众志成城"),
    ("坤", "艮"): ("地山谦", "谦受益"),
    ("坤", "巽"): ("地风升", "循序而升"),
    ("坤", "离"): ("地火明夷", "晦而守正"),
    ("坤", "兑"): ("地泽临", "临事以德"),
    ("震", "乾"): ("雷天大壮", "壮而宜节"),
    ("震", "坤"): ("雷地豫", "乐而有节"),
    ("震", "震"): ("震为雷", "动中有警"),
    ("震", "坎"): ("雷水解", "疏解困局"),
    ("震", "艮"): ("雷山小过", "小步谨慎"),
    ("震", "巽"): ("雷风恒", "持恒有常"),
    ("震", "离"): ("雷火丰", "丰盛警惕"),
    ("震", "兑"): ("雷泽归妹", "慎择所归"),
    ("坎", "乾"): ("水天需", "待时而动"),
    ("坎", "坤"): ("水地比", "亲比互助"),
    ("坎", "震"): ("水雷屯", "初创维艰"),
    ("坎", "坎"): ("坎为水", "险中求德"),
    ("坎", "艮"): ("水山蹇", "蹇难求援"),
    ("坎", "巽"): ("水风井", "养源济人"),
    ("坎", "离"): ("水火既济", "事成宜稳"),
    ("坎", "兑"): ("水泽节", "节制有度"),
    ("艮", "乾"): ("山天大畜", "蓄德待发"),
    ("艮", "坤"): ("山地剥", "剥极思复"),
    ("艮", "震"): ("山雷颐", "颐养正道"),
    ("艮", "坎"): ("山水蒙", "启蒙求教"),
    ("艮", "艮"): ("艮为山", "止于至善"),
    ("艮", "巽"): ("山风蛊", "振敝革新"),
    ("艮", "离"): ("山火贲", "文质彬彬"),
    ("艮", "兑"): ("山泽损", "损有余补不足"),
    ("巽", "乾"): ("风天小畜", "小有积蓄"),
    ("巽", "坤"): ("风地观", "观而后行"),
    ("巽", "震"): ("风雷益", "损上益下"),
    ("巽", "坎"): ("风水涣", "涣散宜聚"),
    ("巽", "艮"): ("风山渐", "循序渐进"),
    ("巽", "巽"): ("巽为风", "柔顺深入"),
    ("巽", "离"): ("风火家人", "齐家定分"),
    ("巽", "兑"): ("风泽中孚", "诚信感通"),
    ("离", "乾"): ("火天大有", "丰有守中"),
    ("离", "坤"): ("火地晋", "光明进取"),
    ("离", "震"): ("火雷噬嗑", "明断决疑"),
    ("离", "坎"): ("火水未济", "未竟宜慎"),
    ("离", "艮"): ("火山旅", "行旅自持"),
    ("离", "巽"): ("火风鼎", "鼎新革故"),
    ("离", "离"): ("离为火", "光明附丽"),
    ("离", "兑"): ("火泽睽", "异中求同"),
    ("兑", "乾"): ("泽天夬", "决而能和"),
    ("兑", "坤"): ("泽地萃", "荟萃聚合"),
    ("兑", "震"): ("泽雷随", "随时而安"),
    ("兑", "坎"): ("泽水困", "困中守志"),
    ("兑", "艮"): ("泽山咸", "感应真诚"),
    ("兑", "巽"): ("泽风大过", "非常之举"),
    ("兑", "离"): ("泽火革", "变革更新"),
    ("兑", "兑"): ("兑为泽", "和悦交流"),
}

YAO_NAMES = ("初爻", "二爻", "三爻", "四爻", "五爻", "上爻")


def year_branch_num(year: int) -> int:
    """公元年 → 地支序数 1=子 … 12=亥"""
    return (year - 4) % 12 + 1


def hour_to_shichen(hour: int) -> str:
    hour = hour % 24
    if hour == 23 or hour < 1:
        return "子"
    for start, name in reversed(HOUR_TO_SHICHEN):
        if hour >= start:
            return name
    return "子"


def normalize_shichen(raw: str) -> str | None:
    raw = raw.strip().replace("时", "").replace("時", "")
    if raw in SHICHEN:
        return raw
    m = re.search(r"(\d{1,2})\s*点", raw)
    if m:
        return hour_to_shichen(int(m.group(1)))
    m = re.search(r"(\d{1,2}):(\d{2})", raw)
    if m:
        return hour_to_shichen(int(m.group(1)))
    return None


def parse_birth_date(text: str) -> tuple[int, int, int] | None:
    m = re.search(r"(19|20)\d{2}[-/年.](\d{1,2})[-/月.](\d{1,2})", text)
    if m:
        y, mo, d = int(m.group(0)[:4]), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return y, mo, d
    m = re.search(r"(19|20)\d{2}(\d{2})(\d{2})", text)
    if m:
        y, mo, d = int(m.group(0)[:4]), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return y, mo, d
    return None


def parse_fortune_query(text: str) -> dict:
    """从自然语言提取算命字段；返回 dict，含 missing 列表。"""
    info: dict = {
        "name": None,
        "gender": None,
        "birth": None,
        "shichen": None,
        "raw": text,
        "missing": [],
    }

    g = re.search(r"(性别[:：\s]*)?(男|女)", text)
    if g:
        info["gender"] = g.group(2)

    birth = parse_birth_date(text)
    if birth:
        info["birth"] = f"{birth[0]:04d}-{birth[1]:02d}-{birth[2]:02d}"
        info["birth_tuple"] = birth

    for key in SHICHEN:
        if key + "时" in text or re.search(rf"(?<![年月日]){key}(?![年月日])", text):
            # 避免把「辰」误匹配日期里的字；优先显式「X时」
            if key + "时" in text or key + "時" in text:
                info["shichen"] = key
                break
    if not info["shichen"]:
        hm = re.search(r"(\d{1,2})\s*[点:：]", text)
        if hm:
            info["shichen"] = hour_to_shichen(int(hm.group(1)))

    # 姓名：显式标注，或「算命：张三，…」
    nm = re.search(r"(?:姓名|名字)[:：\s]*([^\s,，、]{1,8})", text)
    if nm:
        info["name"] = nm.group(1).strip()
    else:
        nm = re.search(
            r"(?:算命|排盘|起卦|推命)[:：\s]*([^\s,，、男女性]{1,8})",
            text,
        )
        if nm:
            info["name"] = nm.group(1).strip()
        else:
            # 「张三，男，1990…」
            nm = re.search(
                r"^[\s\"']*([^\s,，、]{1,8})\s*[,，]\s*(男|女)",
                text,
            )
            if nm:
                info["name"] = nm.group(1).strip()
                if not info["gender"]:
                    info["gender"] = nm.group(2)

    for field, label in (
        ("name", "姓名"),
        ("gender", "性别"),
        ("birth", "出生年月日"),
        ("shichen", "时辰"),
    ):
        if not info.get(field):
            info["missing"].append(label)

    return info


def has_fortune_intent(text: str) -> bool:
    keys = ("算命", "易经", "排盘", "本命卦", "起卦", "推命", "看运势", "运势如何", "批命")
    if any(k in text for k in keys):
        return True
    # 四要素齐备也视为意图
    info = parse_fortune_query(text)
    return len(info["missing"]) == 0


def mod_n(value: int, n: int) -> int:
    r = value % n
    return n if r == 0 else r


def cast_hexagram(year: int, month: int, day: int, shichen: str) -> dict:
    year_n = year_branch_num(year)
    shi_n = SHICHEN[shichen]
    upper_n = mod_n(year_n + month + day, 8)
    lower_n = mod_n(year_n + month + day + shi_n, 8)
    yao_n = mod_n(year_n + month + day + shi_n, 6)

    u_name, u_sym, u_img, u_el = TRIGRAMS[upper_n]
    l_name, l_sym, l_img, l_el = TRIGRAMS[lower_n]
    gua_name, keyword = HEXAGRAMS.get((u_name, l_name), (f"{u_name}{l_name}", "审时度势"))

    # 变卦：动爻阴阳翻转（简化：动爻所在卦宫对宫映射）
    # 爻位 1-3 属下卦，4-6 属上卦；翻转对应三爻之一
    changed_upper, changed_lower = upper_n, lower_n
    if yao_n <= 3:
        # 下卦第 yao_n 爻变：用 XOR 位翻转近似（三爻二进制）
        bits = _trigram_bits(lower_n)
        bits[yao_n - 1] = 1 - bits[yao_n - 1]
        changed_lower = _bits_to_trigram(bits)
    else:
        bits = _trigram_bits(upper_n)
        bits[yao_n - 4] = 1 - bits[yao_n - 4]
        changed_upper = _bits_to_trigram(bits)

    cu_name, cu_sym, cu_img, cu_el = TRIGRAMS[changed_upper]
    cl_name, cl_sym, cl_img, cl_el = TRIGRAMS[changed_lower]
    bian_name, bian_kw = HEXAGRAMS.get((cu_name, cl_name), (f"{cu_name}{cl_name}", "转机在前"))

    return {
        "year_branch_num": year_n,
        "shichen": shichen,
        "shichen_num": shi_n,
        "upper": {"n": upper_n, "name": u_name, "symbol": u_sym, "image": u_img, "element": u_el},
        "lower": {"n": lower_n, "name": l_name, "symbol": l_sym, "image": l_img, "element": l_el},
        "moving_yao": yao_n,
        "moving_yao_name": YAO_NAMES[yao_n - 1],
        "ben_gua": {"name": gua_name, "keyword": keyword, "display": f"{u_sym}{l_sym}"},
        "bian_gua": {"name": bian_name, "keyword": bian_kw, "display": f"{cu_sym}{cl_sym}"},
        "calc": {
            "upper_expr": f"({year_n}+{month}+{day})%8 → {upper_n} {u_name}",
            "lower_expr": f"({year_n}+{month}+{day}+{shi_n})%8 → {lower_n} {l_name}",
            "yao_expr": f"({year_n}+{month}+{day}+{shi_n})%6 → {yao_n}",
        },
    }


def _trigram_bits(n: int) -> list[int]:
    # 1乾111 2兑011 3离101 4震001 5巽110 6坎010 7艮100 8坤000（下→上）
    table = {
        1: [1, 1, 1], 2: [1, 1, 0], 3: [1, 0, 1], 4: [1, 0, 0],
        5: [0, 1, 1], 6: [0, 1, 0], 7: [0, 0, 1], 8: [0, 0, 0],
    }
    return list(table[n])


def _bits_to_trigram(bits: list[int]) -> int:
    rev = {
        (1, 1, 1): 1, (1, 1, 0): 2, (1, 0, 1): 3, (1, 0, 0): 4,
        (0, 1, 1): 5, (0, 1, 0): 6, (0, 0, 1): 7, (0, 0, 0): 8,
    }
    return rev[tuple(bits)]


# 五行 / 动爻短句库：本地拼装，零 Token
_ELEMENT_TONE = {
    "金": ("果断清明", "宜收敛锋芒、重契约与分寸"),
    "木": ("生长舒展", "宜循序培养、忌急于求成"),
    "水": ("润下智流", "宜蓄势待时、重学习与人脉"),
    "火": ("光明附丽", "宜照见本心、忌虚火外扬"),
    "土": ("厚载包容", "宜稳住根基、重信用与落地"),
}
_YAO_TONE = {
    1: "初爻发动：事情尚在萌芽，宜谨慎起步、少铺摊子。",
    2: "二爻发动：得中得应，宜借力同行、稳中求进。",
    3: "三爻发动：多有波折，宜止妄动、先理清边界。",
    4: "四爻发动：近君近事，宜谨慎表态、重协作。",
    5: "五爻发动：得位之机，宜担当决断、仍须听谏。",
    6: "上爻发动：物极将变，宜知止知退、转守为攻需看变卦。",
}
_HORIZON = {
    "金": ("近一年重规则与清算旧账", "三年内适于签约定分", "长远以信誉立身"),
    "木": ("近一年重学习与布局", "三年内可见成长曲线", "长远以持续耕耘见功"),
    "水": ("近一年宜蓄水藏锋", "三年内人脉与信息为桥", "长远以智慧化解波澜"),
    "火": ("近一年宜明目标去冗余", "三年内表达与影响力上升", "长远防过刚与分心"),
    "土": ("近一年宜夯实基础", "三年内项目落地为要", "长远以厚德载物得众"),
}


def compose_reading(name: str, gender: str, birth: str, gua: dict) -> str:
    """模板化解读：无网络、无 LLM，延迟极低且 Token=0。"""
    ben, bian = gua["ben_gua"], gua["bian_gua"]
    ue, le = gua["upper"]["element"], gua["lower"]["element"]
    u_tone, u_tip = _ELEMENT_TONE.get(ue, ("审时度势", "宜守中"))
    l_tone, l_tip = _ELEMENT_TONE.get(le, ("稳妥行事", "宜量力"))
    yao = _YAO_TONE.get(gua["moving_yao"], "动爻提示：当机则变，不可胶柱。")
    h1, h2, h3 = _HORIZON.get(ue, ("近一年宜守", "三年内宜调", "长远宜稳"))

    return (
        f"{name}（{gender}）生于 {birth} {gua['shichen']}时。\n\n"
        f"【命局提要】本卦【{ben['name']}】，象曰「{ben['keyword']}」；"
        f"上{gua['upper']['name']}（{gua['upper']['image']}·{ue}）主气质偏「{u_tone}」，"
        f"下{gua['lower']['name']}（{gua['lower']['image']}·{le}）主处事偏「{l_tone}」。"
        f"宜以「{ben['keyword']}」自持。\n\n"
        f"【本卦 · 变卦】动爻在{gua['moving_yao_name']}。{yao}"
        f"变卦【{bian['name']}】象曰「{bian['keyword']}」，为转机方向："
        f"遇阻时由「{ben['keyword']}」转向「{bian['keyword']}」。\n\n"
        f"【性格与课题】外象近{gua['upper']['image']}，内用借{gua['lower']['image']}之德；"
        f"{u_tip}；{l_tip}。课题在刚柔相济，进退有度。\n\n"
        f"【运势走势】{h1}；{h2}；{h3}。"
        f"近阶段少做无谓扩张，逢变卦之机再主动求变。\n\n"
        f"【开运建议】①每日留片刻静心；②大事先问长期利益与礼；"
        f"③关系多倾听，事业重小步复利。\n\n"
        f"声明：传统文化趣味咨询，非科学预测，不替代医疗、法律或投资决策。"
    )


def brief_for_chat(name: str, gua: dict, out_path: str, metrics: dict) -> str:
    """给对话层直接转述的短摘要，避免模型再扩写。"""
    fname = Path(out_path).name
    return (
        f"{name}：本卦{gua['ben_gua']['name']}（{gua['ben_gua']['keyword']}）→"
        f"变卦{gua['bian_gua']['name']}（{gua['bian_gua']['keyword']}），"
        f"动爻{gua['moving_yao_name']}。"
        f"页面 /fortune/{fname}；"
        f"Skill用时{metrics.get('elapsed_s')}s，Token {metrics.get('total_tokens', 0)}。"
    )


def llm_reading(name: str, gender: str, birth: str, gua: dict) -> tuple[str, dict]:
    """LLM 解读；失败则回落模板。"""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "model": ""}
    try:
        from src.llm_config import get_chat_client, current_model_info
        info = current_model_info()
        usage["model"] = info.get("model", "")
        client, model = get_chat_client()
    except Exception as e:
        text = compose_reading(name, gender, birth, gua)
        text += f"\n\n（未调用 LLM，使用规则解读：{e}）"
        return text, usage

    system = (
        "你是沉稳的易经顾问。根据给定本卦/变卦写运势解读，正文严格控制在 1200 字以内。"
        "语气鼓励、禁止恐吓与绝对吉凶。结构用小标题："
        "命局提要、本卦变卦、性格与课题、运势走势（近1年/3年/5～10年）、"
        "开运建议、免责声明。使用简体中文，纯文本，不要 Markdown 代码块，不要输出思考过程。"
    )
    user = (
        f"姓名：{name}\n性别：{gender}\n出生：{birth} {gua['shichen']}时\n"
        f"推算：{gua['calc']}\n"
        f"本卦：{gua['ben_gua']['name']}（{gua['ben_gua']['keyword']}）{gua['ben_gua']['display']}\n"
        f"动爻：{gua['moving_yao_name']}\n"
        f"变卦：{gua['bian_gua']['name']}（{gua['bian_gua']['keyword']}）{gua['bian_gua']['display']}\n"
        "请直接给出最终解读正文。"
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
        max_tokens=1800,
        stream=False,
    )
    text = (resp.choices[0].message.content or "").strip()
    u = getattr(resp, "usage", None)
    if u is not None:
        usage["prompt_tokens"] = int(getattr(u, "prompt_tokens", 0) or 0)
        usage["completion_tokens"] = int(getattr(u, "completion_tokens", 0) or 0)
        usage["total_tokens"] = int(getattr(u, "total_tokens", 0) or 0)
    if not text:
        text = compose_reading(name, gender, birth, gua)
    return text, usage


_BAGUA_SVG_CACHE: str | None = None


def _bagua_svg() -> str:
    """内联八卦圆环背景（模块级缓存，避免重复拼字符串）。"""
    global _BAGUA_SVG_CACHE
    if _BAGUA_SVG_CACHE is not None:
        return _BAGUA_SVG_CACHE
    nodes = [
        (50, 12, "☰", "乾"), (78, 22, "☴", "巽"), (88, 50, "☵", "坎"),
        (78, 78, "☶", "艮"), (50, 88, "☷", "坤"), (22, 78, "☳", "震"),
        (12, 50, "☲", "离"), (22, 22, "☱", "兑"),
    ]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
        'preserveAspectRatio="xMidYMid meet">',
        '<circle cx="50" cy="50" r="46" fill="none" stroke="#1a3a2a" '
        'stroke-width="0.4" opacity="0.35"/>',
        '<circle cx="50" cy="50" r="30" fill="none" stroke="#1a3a2a" '
        'stroke-width="0.3" opacity="0.25"/>',
        '<text x="50" y="53" text-anchor="middle" font-size="8" '
        'fill="#1a3a2a" opacity="0.2" font-family="serif">太极</text>',
    ]
    for x, y, sym, label in nodes:
        parts.append(
            f'<text x="{x}" y="{y}" text-anchor="middle" font-size="7" '
            f'fill="#1a3a2a" opacity="0.28" font-family="serif">{sym}</text>'
        )
        parts.append(
            f'<text x="{x}" y="{y + 5}" text-anchor="middle" font-size="3" '
            f'fill="#1a3a2a" opacity="0.22" font-family="serif">{label}</text>'
        )
    parts.append("</svg>")
    _BAGUA_SVG_CACHE = "".join(parts)
    return _BAGUA_SVG_CACHE


def render_html(
    name: str,
    gender: str,
    birth: str,
    gua: dict,
    reading: str,
    metrics: dict,
    generated_at: str,
) -> str:
    """纯 Python 字符串动态拼装，不使用模板文件 / 页面生成器。"""
    def esc(s: str) -> str:
        return html.escape(s, quote=True)

    paras = "".join(
        f"<p>{esc(p.strip())}</p>" for p in reading.split("\n") if p.strip()
    )
    bagua = _bagua_svg()
    ben, bian = gua["ben_gua"], gua["bian_gua"]

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{esc(name)} · 易经运势简札</title>
<style>
:root {{
  --ink: #14241c;
  --muted: #3d5c4a;
  --paper: #e8efe6;
  --card: rgba(248, 252, 248, 0.88);
  --line: rgba(26, 58, 42, 0.18);
  --accent: #1f6b4a;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; min-height: 100vh;
  font-family: "Source Han Serif SC", "Noto Serif SC", "Songti SC",
               "SimSun", Georgia, serif;
  color: var(--ink);
  background: radial-gradient(ellipse at 30% 20%, #f3f7f2 0%, var(--paper) 55%, #d5e0d6 100%);
}}
.bg {{
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  display: flex; align-items: center; justify-content: center;
  opacity: 1;
}}
.bg svg {{ width: min(92vmin, 820px); height: min(92vmin, 820px); }}
.wrap {{
  position: relative; z-index: 1;
  max-width: 720px; margin: 0 auto; padding: 2.5rem 1.25rem 3rem;
}}
header {{
  text-align: center; margin-bottom: 1.75rem;
}}
header .seal {{
  display: inline-block; font-size: 0.75rem; letter-spacing: 0.25em;
  color: var(--accent); border: 1px solid var(--accent);
  padding: 0.2rem 0.6rem; margin-bottom: 0.75rem;
}}
h1 {{
  font-weight: 600; font-size: 1.75rem; margin: 0.2rem 0;
  letter-spacing: 0.08em;
}}
.sub {{ color: var(--muted); font-size: 0.95rem; margin: 0.4rem 0 0; }}
.card {{
  background: var(--card);
  border: 1px solid var(--line);
  backdrop-filter: blur(2px);
  padding: 1.25rem 1.35rem;
  margin-bottom: 1rem;
}}
.card h2 {{
  margin: 0 0 0.75rem; font-size: 1.05rem; color: var(--accent);
  letter-spacing: 0.12em; font-weight: 600;
}}
.gua-row {{
  display: flex; gap: 1rem; flex-wrap: wrap;
}}
.gua-box {{
  flex: 1; min-width: 200px;
  border: 1px dashed var(--line); padding: 0.9rem 1rem; text-align: center;
}}
.gua-box .sym {{ font-size: 2rem; line-height: 1.2; }}
.gua-box .name {{ font-size: 1.15rem; margin-top: 0.35rem; }}
.gua-box .kw {{ color: var(--muted); font-size: 0.9rem; margin-top: 0.25rem; }}
.meta {{ font-size: 0.9rem; color: var(--muted); line-height: 1.7; }}
.reading p {{
  margin: 0 0 0.85rem; line-height: 1.85; font-size: 0.98rem;
  text-align: justify;
}}
.metrics {{
  font-size: 0.8rem; color: var(--muted); line-height: 1.6;
  font-family: ui-monospace, Consolas, monospace;
}}
footer {{
  margin-top: 1.5rem; text-align: center;
  font-size: 0.78rem; color: var(--muted);
}}
</style>
</head>
<body>
<div class="bg" aria-hidden="true">{bagua}</div>
<main class="wrap">
  <header>
    <div class="seal">易经运势 · 动态简札</div>
    <h1>{esc(name)} · 运势简札</h1>
    <p class="sub">{esc(gender)} · {esc(birth)} · {esc(gua['shichen'])}时 · 生成于 {esc(generated_at)}</p>
  </header>

  <section class="card">
    <h2>本卦 · 变卦</h2>
    <div class="gua-row">
      <div class="gua-box">
        <div class="sym">{esc(ben['display'])}</div>
        <div class="name">本卦 · {esc(ben['name'])}</div>
        <div class="kw">{esc(ben['keyword'])}</div>
      </div>
      <div class="gua-box">
        <div class="sym">{esc(bian['display'])}</div>
        <div class="name">变卦 · {esc(bian['name'])}</div>
        <div class="kw">{esc(bian['keyword'])}</div>
      </div>
    </div>
    <p class="meta" style="margin-top:0.9rem">
      动爻：{esc(gua['moving_yao_name'])}<br/>
      上卦推算：{esc(gua['calc']['upper_expr'])}<br/>
      下卦推算：{esc(gua['calc']['lower_expr'])}<br/>
      动爻推算：{esc(gua['calc']['yao_expr'])}
    </p>
  </section>

  <section class="card reading">
    <h2>解读</h2>
    {paras}
  </section>

  <section class="card">
    <h2>本次 Skill 指标</h2>
    <div class="metrics">
      elapsed_s: {metrics.get('elapsed_s')}<br/>
      prompt_tokens: {metrics.get('prompt_tokens')}<br/>
      completion_tokens: {metrics.get('completion_tokens')}<br/>
      total_tokens: {metrics.get('total_tokens')}<br/>
      model: {esc(str(metrics.get('model') or '-'))}
    </div>
  </section>

  <footer>传统文化趣味咨询 · 非科学预测 · 每次运行动态生成 · 无外网依赖</footer>
</main>
</body>
</html>
"""


def write_metrics(out_dir: Path, metrics: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = out_dir / "metrics_latest.json"
    latest.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    log = out_dir / "metrics_log.jsonl"
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(metrics, ensure_ascii=False) + "\n")


def run(
    name: str,
    gender: str,
    birth: str,
    shichen: str,
    out_dir: Path,
    use_llm: bool = True,
) -> dict:
    t0 = time.perf_counter()
    y, m, d = (int(x) for x in birth.split("-"))
    gua = cast_hexagram(y, m, d, shichen)
    mode = "llm" if use_llm else "template"
    if use_llm:
        reading, usage = llm_reading(name, gender, birth, gua)
    else:
        reading = compose_reading(name, gender, birth, gua)
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "model": ""}

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", name) or "user"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{safe_name}_{stamp}.html"

    metrics = {
        "skill": "yijing-sizhu-gua",
        "mode": mode,
        "input": {
            "name": name,
            "gender": gender,
            "birth": birth,
            "shichen": shichen,
        },
        "ben_gua": gua["ben_gua"]["name"],
        "bian_gua": gua["bian_gua"]["name"],
        "elapsed_s": 0.0,
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "total_tokens": usage["total_tokens"],
        "model": usage.get("model") or "",
        "output_path": str(out_path.resolve()),
        "generated_at": generated_at,
    }

    metrics["elapsed_s"] = round(time.perf_counter() - t0, 4)
    metrics["output_path"] = str(out_path.resolve())
    out_path.write_text(
        render_html(name, gender, birth, gua, reading, metrics, generated_at),
        encoding="utf-8",
    )
    metrics["elapsed_s"] = round(time.perf_counter() - t0, 4)
    write_metrics(out_dir, metrics)

    brief = brief_for_chat(name, gua, str(out_path), metrics)
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
            "mode": mode,
            "brief": brief,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="四柱起卦运势 HTML 动态生成")
    parser.add_argument("text", nargs="?", help="自然语言，如：算命：李明，男，1990-08-15，辰时")
    parser.add_argument("--name", default="")
    parser.add_argument("--gender", default="")
    parser.add_argument("--birth", default="", help="YYYY-MM-DD")
    parser.add_argument("--shichen", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="仅用本地模板解读（默认调用 LLM）",
    )
    args = parser.parse_args(argv)

    if args.text:
        info = parse_fortune_query(args.text)
    else:
        info = {
            "name": args.name or None,
            "gender": args.gender or None,
            "birth": args.birth or None,
            "shichen": normalize_shichen(args.shichen) if args.shichen else None,
            "missing": [],
        }
        # CLI 覆盖
        if args.name:
            info["name"] = args.name
        if args.gender:
            info["gender"] = args.gender
        if args.birth:
            info["birth"] = args.birth
            bt = parse_birth_date(args.birth)
            if bt:
                info["birth"] = f"{bt[0]:04d}-{bt[1]:02d}-{bt[2]:02d}"
        if args.shichen:
            info["shichen"] = normalize_shichen(args.shichen)
        for field, label in (
            ("name", "姓名"),
            ("gender", "性别"),
            ("birth", "出生年月日"),
            ("shichen", "时辰"),
        ):
            if not info.get(field):
                info["missing"].append(label)

    # 命令行显式参数可补全 text 解析结果
    if args.name:
        info["name"] = args.name
    if args.gender:
        info["gender"] = args.gender
    if args.birth:
        bt = parse_birth_date(args.birth) or parse_birth_date(args.birth.replace("-", ""))
        if bt:
            info["birth"] = f"{bt[0]:04d}-{bt[1]:02d}-{bt[2]:02d}"
        else:
            info["birth"] = args.birth
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
        err = {
            "ok": False,
            "error": "信息不完整，缺少：" + "、".join(info["missing"]),
            "missing": info["missing"],
        }
        print(json.dumps(err, ensure_ascii=False))
        return 2

    try:
        result = run(
            name=info["name"],
            gender=info["gender"],
            birth=info["birth"],
            shichen=info["shichen"],
            out_dir=Path(args.out_dir),
            use_llm=not bool(args.no_llm),
        )
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
