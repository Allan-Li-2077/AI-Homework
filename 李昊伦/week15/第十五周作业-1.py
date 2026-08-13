"""
Tavily 联网搜索封装（零额外依赖，用标准库 urllib）

教学定位：市场调研需要实时信息，Tavily 是为 LLM 优化的搜索 API（返回摘要 + 来源）。
用 urllib 而非 requests，避免引入新依赖（CLAUDE.md 少依赖原则）。

使用方式：
  from tavily_search import tavily_search
  r = tavily_search("中国新能源汽车2024销量")
  # r = {"answer": "...", "results": [{"title","url","content"}], "response_time": ...}

依赖：环境变量 TAVILY_API_KEY
"""
import os, json, urllib.request, logging
from html.parser import HTMLParser
logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


class _TextExtractor(HTMLParser):
    """极简 HTML 正文提取：去掉 script/style/nav，保留段落文本。"""
    SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self, max_chars: int = 3000) -> str:
        joined = " ".join(self._parts)
        return joined[:max_chars]


def extract_content(url: str, max_chars: int = 3000) -> str:
    """抓取网页正文摘要。用标准库 urllib + html.parser，零额外依赖。
    失败返回错误描述字符串（不抛异常，ReAct 兜底）。"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            # 尝试检测编码
            ct = resp.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in ct:
                charset = ct.split("charset=")[-1].strip().split(";")[0]
            html = raw.decode(charset, errors="replace")

        parser = _TextExtractor()
        parser.feed(html)
        text = parser.get_text(max_chars)
        return text if text else "页面无正文内容"
    except Exception as e:
        return f"抓取失败: {type(e).__name__}: {str(e)[:100]}"


def tavily_search(query: str, max_results: int = 5) -> dict:
    """调用 Tavily 搜索。返回 {answer, results, response_time}。
    失败返回 {"error": ...}，不抛异常（ReAct loop 兜底）。"""
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return {"error": "未设置 TAVILY_API_KEY"}
    payload = {
        "api_key": key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": True,
    }
    try:
        req = urllib.request.Request(
            TAVILY_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # 精简结果，只留对 LLM 有用的字段
        results = [{"title": r.get("title", ""), "url": r.get("url", ""),
                     "content": (r.get("content") or "")[:600]}
                    for r in data.get("results", [])]
        return {"answer": data.get("answer") or "",
                "results": results,
                "response_time": data.get("response_time")}
    except Exception as e:
        logger.warning(f"Tavily 搜索失败 '{query}': {e}")
        return {"error": f"{type(e).__name__}: {str(e)[:100]}"}


def format_search_result(r: dict) -> str:
    """把 Tavily 返回格式化成喂给 LLM 的文本。每条结果带 URL 方便 extract_content 深入。"""
    if "error" in r:
        return f"搜索失败: {r['error']}"
    parts = []
    if r.get("answer"):
        parts.append(f"摘要: {r['answer']}")
    for i, res in enumerate(r.get("results", []), 1):
        url = res.get("url", "")
        parts.append(f"[{i}] {res['title']}\n    URL: {url}\n    {res['content'][:300]}")
    return "\n".join(parts) if parts else "无结果"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = tavily_search("中国新能源汽车2024年销量")
    print(format_search_result(r)[:400])
    # 测试 extract_content
    if r.get("results"):
        url = r["results"][0]["url"]
        print(f"\n--- extract_content({url[:60]}...) ---")
        print(extract_content(url)[:500])
