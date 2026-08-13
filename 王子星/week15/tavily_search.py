"""
Tavily 联网搜索封装（requests 版）

"""
import os
import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
SCORE_THRESHOLD = 0.2  # 低于此相关度的结果直接丢弃，减少噪音喂给模型


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def tavily_search(query: str, max_results: int = 5, search_depth: str = "basic",
                   include_domains: list[str] | None = None) -> dict:
    """调用 Tavily 搜索。

    search_depth: "basic"（快）或 "advanced"（更全面但更慢，适合深度调研子课题）
    include_domains: 限定搜索的域名列表（可选），用于金融问题时优先权威来源

    返回 {"answer": str, "results": [{"title","url","domain","score","content"}], "response_time": float}
    失败返回 {"error": "..."}，不抛异常，交给上层 ReAct/Function Calling 兜底。
    """
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return {"error": "未设置 TAVILY_API_KEY 环境变量"}

    payload = {
        "api_key": key,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": True,
    }
    if include_domains:
        payload["include_domains"] = include_domains

    try:
        resp = requests.post(TAVILY_URL, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.Timeout:
        return {"error": "Tavily 请求超时"}
    except requests.HTTPError as e:
        return {"error": f"Tavily HTTP错误: {e}"}
    except requests.RequestException as e:
        return {"error": f"Tavily 请求失败: {e}"}
    except ValueError as e:
        return {"error": f"Tavily 返回非 JSON: {e}"}

    results = []
    for r in data.get("results", []):
        score = r.get("score")
        if score is not None and score < SCORE_THRESHOLD:
            continue
        url = r.get("url", "")
        results.append({
            "title": r.get("title", ""),
            "url": url,
            "domain": _domain(url),
            "score": score,
            "content": (r.get("content") or "")[:600],
        })

    return {
        "answer": data.get("answer") or "",
        "results": results,
        "response_time": data.get("response_time"),
    }


def format_search_result(r: dict) -> str:
    """把 tavily_search 的返回格式化成喂给 LLM 的文本，带编号引用和来源域名。"""
    if "error" in r:
        return f"[联网搜索失败] {r['error']}"

    parts = []
    if r.get("answer"):
        parts.append(f"摘要: {r['answer']}")

    for i, res in enumerate(r.get("results", []), 1):
        score_tag = f" 相关度{res['score']:.2f}" if res.get("score") is not None else ""
        parts.append(
            f"[{i}] {res['title']} (来源: {res['domain']}{score_tag})\n"
            f"    {res['content'][:300]}"
        )

    return "\n".join(parts) if parts else "未搜索到相关结果"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = tavily_search("2024年英伟达全年营收")
    print(format_search_result(r)[:500])
