"""博查 Bocha 联网搜索封装
定位：所有 agent 的联网能力都来自这里（主 agent 和子 agent 共用）。
依赖：pip install requests；环境变量 BOCHA_API_KEY
"""

import os
import requests
import logging

logger = logging.getLogger(__name__)
BOCHA_SEARCH_URL = "https://api.bochaai.com/v1/web-search"

def bocha_search(query: str, max_results: int = 5) -> dict:
    """调用博查搜索。返回 {results:[{title,url,content}]}。
    失败返回 {"error": ...}，不抛异常（ReAct loop 兜底）。"""
    key = os.getenv("BOCHA_API_KEY")
    if not key:
        return {"error": "未设置 BOCHA_API_KEY"}

    payload = {
        "query": query,
        "count": max_results,
        "summary": True,
        "freshness": "noLimit"
    }

    try:
        response = requests.post(
            BOCHA_SEARCH_URL,
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        pages = ((data.get("data") or {}).get("webPages") or {}).get("value") or []
        results = [
            {
                "title": p.get("name", ""),
                "url": p.get("url", ""),
                "content": (p.get("summary") or p.get("snippet") or "")[:600]
            }
            for p in pages
        ]
        return {"answer": "", "results": results}
    except requests.RequestException as e:
        logger.warning(f"博查搜索失败 '{query}': {e}")
        return {"error": f"{type(e).__name__}: {str(e)[:100]}"}


def format_search_result(result: dict) -> str:
    """把博查返回格式化成喂给 LLM 的文本。"""
    if "error" in result:
        return f"搜索失败: {result['error']}"
    parts = []
    for i, res in enumerate(result.get("results", []), 1):
        parts.append(f"[{i}] {res['title']}\n    {res['content'][:300]}\n    来源: {res['url']}")
    return "\n".join(parts) if parts else "无结果"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = bocha_search("2025年中国新能源汽车销量")
    print(format_search_result(r)[:500])