"""解析用户翻译意图：支持语言 / 不支持语言 / 待译正文。"""

from __future__ import annotations

import re

# code → (中文标签, LLM 目标说明)
LANGS: dict[str, tuple[str, str]] = {
    "en": ("英文", "English"),
    "ja": ("日文", "Japanese"),
    "fr": ("法语", "French"),
    "ko": ("韩语", "Korean"),
    "ru": ("俄语", "Russian"),
}

# 语言 code → 独立子 Skill 目录名
CODE_TO_SKILL: dict[str, str] = {
    "en": "translate-en",
    "ja": "translate-ja",
    "fr": "translate-fr",
    "ko": "translate-ko",
    "ru": "translate-ru",
}

SKILL_TO_CODE: dict[str, str] = {v: k for k, v in CODE_TO_SKILL.items()}

_SUPPORTED_ALIASES: list[tuple[str, str]] = [
    ("english", "en"),
    ("japanese", "ja"),
    ("french", "fr"),
    ("korean", "ko"),
    ("russian", "ru"),
    ("英文", "en"),
    ("英语", "en"),
    ("日文", "ja"),
    ("日语", "ja"),
    ("法语", "fr"),
    ("法文", "fr"),
    ("韩语", "ko"),
    ("韩文", "ko"),
    ("朝鮮語", "ko"),
    ("朝鲜语", "ko"),
    ("俄语", "ru"),
    ("俄文", "ru"),
]

# 明确不支持的目标语言（命中后提示固定文案）
_UNSUPPORTED_ALIASES: list[tuple[str, str]] = [
    ("german", "德语"),
    ("chinese", "汉语"),
    ("spanish", "西班牙语"),
    ("italian", "意大利语"),
    ("portuguese", "葡萄牙语"),
    ("arabic", "阿拉伯语"),
    ("thai", "泰语"),
    ("vietnamese", "越南语"),
    ("hindi", "印地语"),
    ("dutch", "荷兰语"),
    ("swedish", "瑞典语"),
    ("polish", "波兰语"),
    ("turkish", "土耳其语"),
    ("greek", "希腊语"),
    ("latin", "拉丁语"),
    ("德语", "德语"),
    ("德文", "德语"),
    ("汉语", "汉语"),
    ("中文", "汉语"),
    ("西班牙语", "西班牙语"),
    ("西班牙文", "西班牙语"),
    ("西语", "西班牙语"),
    ("意大利语", "意大利语"),
    ("意大利文", "意大利语"),
    ("意语", "意大利语"),
    ("葡萄牙语", "葡萄牙语"),
    ("葡萄牙文", "葡萄牙语"),
    ("阿拉伯语", "阿拉伯语"),
    ("阿拉伯文", "阿拉伯语"),
    ("泰语", "泰语"),
    ("泰文", "泰语"),
    ("越南语", "越南语"),
    ("越南文", "越南语"),
    ("印地语", "印地语"),
    ("荷兰语", "荷兰语"),
    ("瑞典语", "瑞典语"),
    ("波兰语", "波兰语"),
    ("土耳其语", "土耳其语"),
    ("希腊语", "希腊语"),
    ("拉丁语", "拉丁语"),
    ("粤语", "粤语"),
    ("繁体", "繁体中文"),
    ("繁體", "繁体中文"),
]

UNSUPPORTED_MSG = "抱歉，不支持翻译该种语言"

_TRANSLATE_INTENT = re.compile(
    r"(翻译|译成|翻成|译为|翻为|translate\s+to|translate\s+into|translation)",
    re.IGNORECASE,
)

# 「翻译成功英文」≈「翻译成英文」常见连写/笔误
_NORMALIZE_SUCCESS_TYPO = re.compile(
    r"翻译成功(?="
    r"英文|英语|日文|日语|法语|法文|韩语|韩文|俄语|俄文|"
    r"english|japanese|french|korean|russian|"
    r"[、,，/|与和及]|[:：]|\s*$"
    r")",
    re.IGNORECASE,
)

_STRIP_PATTERNS = [
    re.compile(
        r"(?:请)?(?:把|将)?(?:这段话|这段|下列|下面|如下)?(?:文字|内容|句子|文本)?"
        r"(?:翻译成功|翻译成|翻译为|翻译到|译成|翻成|译为|翻为|翻译)",
        re.IGNORECASE,
    ),
    re.compile(r"translate\s+(?:this\s+)?(?:into|to)", re.IGNORECASE),
    re.compile(r"[:：]\s*$"),
]

_UNKNOWN_LANG_RE = re.compile(
    r"(?:翻译成功|翻译成|翻译为|翻译到|译成|翻成|译为|翻为|翻译)\s*"
    r"([A-Za-z\u4e00-\u9fff]{1,12}?(?:语|文|語))",
)

_SOURCE_JUNK = re.compile(
    r"(?:^|[\s])(?:成功|成|为|到|至|成成功)(?=[\s:：,，、]|$)"
)


def normalize_query(text: str) -> str:
    """规范用户输入，消除「翻译成功英文」这类连写。"""
    if not text:
        return text
    return _NORMALIZE_SUCCESS_TYPO.sub("翻译成", text)


def _scan_aliases(text: str, aliases: list[tuple[str, str]]) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    lower = text.lower()
    for alias, value in aliases:
        start = 0
        needle = alias.lower() if alias.isascii() else alias
        haystack = lower if alias.isascii() else text
        while True:
            idx = haystack.find(needle, start)
            if idx < 0:
                break
            hits.append((idx, value))
            start = idx + len(needle)
    hits.sort(key=lambda x: x[0])
    return hits


def detect_targets(text: str) -> list[str]:
    found: list[str] = []
    for _, code in _scan_aliases(text, _SUPPORTED_ALIASES):
        if code not in found:
            found.append(code)
    return found


def _contains_supported_alias(token: str) -> bool:
    low = token.lower()
    for alias, _ in _SUPPORTED_ALIASES:
        if alias.isascii():
            if alias.lower() in low:
                return True
        elif alias in token:
            return True
    return False


def detect_unsupported(text: str) -> list[str]:
    """返回不支持语言的展示名（去重，保序）。"""
    text = normalize_query(text)
    found: list[str] = []
    for _, label in _scan_aliases(text, _UNSUPPORTED_ALIASES):
        if label not in found:
            found.append(label)

    supported_alias_set = {a for a, _ in _SUPPORTED_ALIASES}
    for m in _UNKNOWN_LANG_RE.finditer(text):
        token = m.group(1).strip()
        if not token:
            continue
        if token in supported_alias_set or token.lower() in {
            a.lower() for a in supported_alias_set if a.isascii()
        }:
            continue
        if _contains_supported_alias(token):
            continue
        if any(token == a or token in a or a in token for a, _ in _UNSUPPORTED_ALIASES):
            if token not in found and not any(token in x or x in token for x in found):
                for a, label in _UNSUPPORTED_ALIASES:
                    if token == a or token in a or a in token:
                        if label not in found:
                            found.append(label)
                        break
            continue
        if token in ("语言", "語", "外语", "外國語", "外国语"):
            continue
        if token not in found:
            found.append(token)
    return found


def has_translate_intent(text: str) -> bool:
    if not text or not text.strip():
        return False
    if _TRANSLATE_INTENT.search(text):
        return True
    if re.search(r"multi-lang-translate|translate-(?:en|ja|fr|ko|ru)\b", text, re.IGNORECASE):
        return True
    return False


def extract_source(text: str, targets: list[str] | None = None) -> str:
    cleaned = normalize_query(text)
    cleaned = re.sub(
        r"(?:/skill\s+|@skill\s+|@)(?:multi-lang-translate|translate-(?:en|ja|fr|ko|ru))\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    for pat in _STRIP_PATTERNS:
        cleaned = pat.sub(" ", cleaned)

    for alias, _ in _SUPPORTED_ALIASES + [(a, "") for a, _ in _UNSUPPORTED_ALIASES]:
        if alias.isascii():
            cleaned = re.sub(re.escape(alias), " ", cleaned, flags=re.IGNORECASE)
        else:
            cleaned = cleaned.replace(alias, " ")

    cleaned = _SOURCE_JUNK.sub(" ", cleaned)
    cleaned = re.sub(r"[、,，/|与和及以及\s]+", " ", cleaned)
    cleaned = re.sub(r"^[\s:：,，、；;]+|[\s:：,，、；;]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"^成功[\s:：]*", "", cleaned).strip()
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", cleaned):
        return ""
    return cleaned


def parse_query(text: str) -> dict:
    text = normalize_query(text)
    targets = detect_targets(text)
    unsupported = detect_unsupported(text)
    source = extract_source(text, targets)
    return {
        "has_intent": has_translate_intent(text),
        "targets": targets,
        "unsupported": unsupported,
        "source": source,
        "supported": [{"code": c, "label": LANGS[c][0], "skill": CODE_TO_SKILL[c]} for c in LANGS],
    }
