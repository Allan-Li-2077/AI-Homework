"""
网络搜索工具 - 使用 DuckDuckGo 零依赖实现
"""
import json
import urllib.request
import urllib.parse
import re
from typing import Optional


def duckduckgo_search(query: str, max_results: int = 5) -> dict:
    """
    使用 DuckDuckGo HTML 搜索（零 API key 依赖）

    Args:
        query: 搜索query
        max_results: 最大结果数

    Returns:
        {"answer": str, "results": [{"title": str, "url": str, "snippet": str}, ...]}
    """
    try:
        # 编码 query
        encoded_q = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_q}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode("utf-8")

        # 解析结果
        results = []
        # DuckDuckGo HTML 格式：<a class="result__a" href="...">title</a>
        # 下面跟着 <a class="result__snippet" href="...">snippet</a>
        link_pattern = re.compile(
            r'<a class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        snippet_pattern = re.compile(
            r'<a class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL
        )

        links = link_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for i, (href, title) in enumerate(links[:max_results]):
            title_text = re.sub(r'<[^>]+>', '', title).strip()
            snippet_text = ""
            if i < len(snippets):
                snippet_text = re.sub(r'<[^>]+>', '', snippets[i]).strip()

            if title_text:
                results.append({
                    "title": title_text,
                    "url": href,
                    "snippet": snippet_text
                })

        # 尝试提取简短答案（Featured Snippet）
        answer = ""
        snippet_match = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        if snippet_match:
            answer = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()

        return {
            "answer": answer,
            "results": results
        }
    except Exception as e:
        return {"error": str(e), "answer": "", "results": []}


def format_search_results(search_result: dict) -> str:
    """将搜索结果格式化为可读字符串"""
    if "error" in search_result:
        return f"搜索失败: {search_result['error']}"

    parts = []
    if search_result.get("answer"):
        parts.append(f"简要回答: {search_result['answer']}")

    if search_result.get("results"):
        parts.append("搜索结果:")
        for r in search_result["results"][:5]:
            parts.append(f"  - {r['title']}")
            parts.append(f"    {r['snippet']}")
            parts.append(f"    链接: {r['url']}")

    return "\n".join(parts) if parts else "未找到相关结果"
