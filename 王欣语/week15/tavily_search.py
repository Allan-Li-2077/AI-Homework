"""
Tavily 联网搜索封装（零额外 SDK 依赖，使用标准库 urllib）

教学要点：
- 市场调研需要实时信息，Tavily 是为 LLM 优化的搜索 API
- 用 urllib 而非 requests，避免引入新依赖
"""
import os
import json
import urllib.request
import logging

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


def tavily_search(query: str, max_results: int = 5) -> dict:
    """
    调用 Tavily 搜索 API
    
    Args:
        query: 搜索查询词
        max_results: 返回结果数量
    
    Returns:
        {"answer": 摘要, "results": [{"title", "url", "content"}], "response_time"}
        失败返回 {"error": ...}
    """
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
        
        # 精简结果，只保留对 LLM 有用的字段
        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": (r.get("content") or "")[:600]
            }
            for r in data.get("results", [])
        ]
        
        return {
            "answer": data.get("answer") or "",
            "results": results,
            "response_time": data.get("response_time")
        }
    except Exception as e:
        logger.warning(f"Tavily 搜索失败 '{query}': {e}")
        return {"error": f"{type(e).__name__}: {str(e)[:100]}"}


def format_search_result(r: dict) -> str:
    """
    把 Tavily 返回格式化成喂给 LLM 的文本
    
    Args:
        r: tavily_search 的返回结果
    
    Returns:
        格式化后的文本
    """
    if "error" in r:
        return f"搜索失败: {r['error']}"
    
    parts = []
    if r.get("answer"):
        parts.append(f"摘要: {r['answer']}")
    
    for i, res in enumerate(r.get("results", []), 1):
        parts.append(f"[{i}] {res['title']}\n    {res['content'][:300]}")
    
    return "\n".join(parts) if parts else "无结果"


if __name__ == "__main__":
    # 自测
    logging.basicConfig(level=logging.INFO)
    r = tavily_search("中国新能源汽车2024年销量")
    print(format_search_result(r)[:400])
