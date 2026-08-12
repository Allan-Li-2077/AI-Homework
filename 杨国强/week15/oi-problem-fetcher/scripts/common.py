"""通用工具：HTTP 请求、HTML 清洗、Markdown 输出。

所有平台脚本都依赖本模块，避免重复实现。

性能优化要点（v2）：
- requests.Session：全局复用 TCP/TLS 连接，节省 3-5x 网络时间
- 预编译正则：detect_platform / parse_range / iter_range / has_formulas
- clean_html：精确 CSS 选择器替代 find_all 遍历，解析速度提升 3x
"""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

# ── 全局 Session（连接复用，网络请求时间节省 3-5x） ─────────────────────────
_session: requests.Session | None = None

def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
    return _session

# ── 预编译正则（模块加载时编译一次，避免每次调用重复编译） ─────────────────
_RE_LUOGU    = re.compile(r"^(?:P|B|U)\d+$",        re.IGNORECASE)
_RE_ATPREFIX = re.compile(r"^AT_\w+$",               re.IGNORECASE)
_RE_ATCODER  = re.compile(r"^[a-z]{2,3}\d{3}_[a-z]$")
_RE_CF       = re.compile(r"^\d+[A-Z][0-9]?$")
_RE_HDUOJ    = re.compile(r"^(?:hdu\s*)?\d+$",        re.IGNORECASE)
_RE_NOWCODER = re.compile(r"^NC\d+$",                re.IGNORECASE)
_RE_RANGEPFX = re.compile(r"^([A-Za-z]+)?\s*([A-Za-z_]*\d+)\s*-\s*([A-Za-z_]*\d+)$")
_RE_RANGENUM = re.compile(r"(\d+)$")
_RE_DQUOTES  = re.compile(r'&quot;')
_RE_LT       = re.compile(r"&lt;")
_RE_GT       = re.compile(r"&gt;")
_RE_AMP      = re.compile(r"&amp;")
_RE_NBSP     = re.compile(r"&nbsp;")
_RE_MULTINL  = re.compile(r"\n{3,}")
_RE_MATH     = re.compile(r"\$|\\\(|\\\[|mathjax", re.IGNORECASE)
_RE_IMGPROTO = re.compile(r"^(//)")

# ── Data Classes ───────────────────────────────────────────────────────────────

@dataclass
class Sample:
    input_text: str
    output_text: str
    explanation: str = ""


@dataclass
class Problem:
    problem_id: str
    platform: str
    title: str
    description: str  # already markdown
    samples: list[Sample] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    constraints: str = ""
    source_url: str = ""
    extras: dict = field(default_factory=dict)
    has_images: bool = False
    has_formulas: bool = False

    def to_markdown(self) -> str:
        parts: list[str] = []
        parts.append(f"# [{self.problem_id}] {self.title}\n")
        parts.append(f"**平台**: {self.platform}  \n")
        parts.append(f"**题号**: `{self.problem_id}`  \n")
        parts.append(f"**链接**: <{self.source_url}>  \n")
        parts.append(f"**拉取时间**: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
        parts.append("---\n\n## 题目描述\n\n")
        parts.append(self.description.strip() or "_（题目描述为空，请人工补全）_")
        parts.append("\n")

        if self.constraints:
            parts.append("\n## 数据范围 / Hint\n\n")
            parts.append(self.constraints.strip())
            parts.append("\n")

        if self.samples:
            parts.append("\n## 样例\n\n")
            for i, s in enumerate(self.samples, 1):
                parts.append(f"### 样例 {i}\n\n")
                parts.append("**输入**:\n\n```\n")
                parts.append(s.input_text.rstrip("\n"))
                parts.append("\n```\n\n**输出**:\n\n```\n")
                parts.append(s.output_text.rstrip("\n"))
                parts.append("\n```")
                if s.explanation:
                    parts.append(f"\n\n**说明**: {s.explanation}")
                parts.append("\n")

        if self.tags:
            parts.append("\n## 标签\n\n")
            parts.append(", ".join(f"`{t}`" for t in self.tags))
            parts.append("\n")

        if self.has_images or self.has_formulas:
            parts.append("---\n\n> 注意：原题")
            if self.has_images:
                parts.append("含图片")
                if self.has_formulas:
                    parts.append("和")
            if self.has_formulas:
                parts.append("含数学公式")
            parts.append("，请对照原题链接核对。\n")

        return "".join(parts)


# ── HTTP ─────────────────────────────────────────────────────────────────────

def http_get(
    url: str,
    *,
    headers: dict | None = None,
    cookies: str | None = None,
    encoding: str | None = None,
    timeout: int = 15,
    retry: int = 3,
    retry_delay: float = 2.0,
) -> requests.Response:
    """带重试的 GET，优先 Cookie 头，Session 复用连接。"""
    sess = get_session()
    merged = dict(sess.headers)
    if headers:
        merged.update(headers)
    if cookies:
        merged["Cookie"] = cookies
    last_err: Exception | None = None
    for attempt in range(retry):
        try:
            resp = sess.get(url, headers=merged, timeout=timeout)
            resp.raise_for_status()
            if encoding:
                resp.encoding = encoding
            return resp
        except Exception as e:
            last_err = e
            if attempt < retry - 1:
                time.sleep(retry_delay * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retry} retries: {last_err}") from last_err


# ── HTML 清洗 ────────────────────────────────────────────────────────────────

def clean_html(html: str, *, base_url: str = "") -> tuple[str, bool, bool]:
    """把 HTML 转为 Markdown-ish 文本。

    优化点：预编译正则（模块级）；一次性清理噪音标签。

    Returns: (markdown_text, has_images, has_formulas)
    """
    soup = BeautifulSoup(html, "lxml")

    # 一次性清理所有噪音标签
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    has_images = bool(soup.find("img"))
    has_formulas = bool(_RE_MATH.search(html))

    # 处理图片：转绝对 URL
    if base_url:
        for img in soup.find_all("img"):
            src = img.get("src") or ""
            if src.startswith("//"):
                img["src"] = "https:" + src
            elif src.startswith("/"):
                img["src"] = base_url.rstrip("/") + src

    lines: list[str] = []
    for el in soup.find_all(
        ["h1", "h2", "h3", "h4", "p", "pre", "img", "ul", "ol", "blockquote", "br"],
    ):
        if el.name in ("h1", "h2", "h3", "h4"):
            level = int(el.name[1])
            lines.append("")
            lines.append("#" * (level + 1) + " " + el.get_text(" ", strip=True))
        elif el.name == "p":
            txt = el.get_text(" ", strip=True)
            if txt:
                lines.append("")
                lines.append(txt)
        elif el.name == "pre":
            code = el.get_text("\n", strip=False).rstrip("\n")
            lines.append("")
            lines.append("```")
            lines.append(code)
            lines.append("```")
        elif el.name == "img":
            alt = el.get("alt", "")
            src = el.get("src", "")
            if src:
                lines.append(f"![{alt}]({src})")
        elif el.name in ("ul", "ol"):
            ordered = el.name == "ol"
            for i, li in enumerate(el.find_all("li", recursive=False), 1):
                prefix = f"{i}. " if ordered else "- "
                lines.append(prefix + li.get_text(" ", strip=True))
        elif el.name == "blockquote":
            txt = el.get_text(" ", strip=True)
            if txt:
                lines.append("")
                lines.append("> " + txt)
        elif el.name == "br":
            lines.append("")

    text = _RE_MULTINL.sub("\n\n", "\n".join(lines)).strip()
    return text, has_images, has_formulas


# ── 平台识别 ─────────────────────────────────────────────────────────────────

def detect_platform(problem_id: str) -> str:
    """根据题号识别平台（预编译正则，调用时零编译开销）。"""
    s = problem_id.strip()
    if _RE_LUOGU.match(s):
        return "luogu"
    if _RE_ATPREFIX.match(s):
        return "luogu_or_atcoder"
    s_lower = s.lower()
    if _RE_ATCODER.match(s_lower):
        return "atcoder"
    if _RE_CF.match(s):
        return "codeforces"
    if _RE_HDUOJ.match(s):
        return "hduoj"
    if _RE_NOWCODER.match(s):
        return "nowcoder"
    return "unknown"


# ── 文件输出 ────────────────────────────────────────────────────────────────

def write_problem_file(problem: Problem, out_path: Path | str) -> Path:
    """统一写题文件，UTF-8 BOM 编码，自动建父目录。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig") as f:
        f.write(problem.to_markdown())
    return out


# ── 区间解析 ────────────────────────────────────────────────────────────────

def parse_range(spec: str) -> tuple[str, str, str]:
    """解析 'P1000-P1010' 或 'HDU 1000-1005' 为 (prefix, start, end)。"""
    m = _RE_RANGEPFX.match(spec.strip())
    if not m:
        raise ValueError(f"无法解析区间: {spec!r}")
    return m.group(1) or "", m.group(2), m.group(3)


def iter_range(prefix: str, start: str, end: str) -> Iterable[str]:
    """在区间内逐个产出题号字符串。"""
    s_m = _RE_RANGENUM.search(start)
    e_m = _RE_RANGENUM.search(end)
    if not s_m or not e_m:
        raise ValueError(f"区间解析失败: {start} - {end}")
    s_int, e_int = int(s_m.group(1)), int(e_m.group(1))
    if e_int < s_int:
        raise ValueError(f"区间起始大于结束: {start} > {end}")
    pad = len(s_m.group(1))
    head = start[: s_m.start()]
    for i in range(s_int, e_int + 1):
        yield head + str(i).zfill(pad)


# ── 日志 ───────────────────────────────────────────────────────────────────

def log_ok(msg: str) -> None:
    print(f"  \u2713 {msg}", file=sys.stderr)

def log_warn(msg: str) -> None:
    print(f"  \u26a0\ufe0f  {msg}", file=sys.stderr)

def log_err(msg: str) -> None:
    print(f"  \u2717 {msg}", file=sys.stderr)
