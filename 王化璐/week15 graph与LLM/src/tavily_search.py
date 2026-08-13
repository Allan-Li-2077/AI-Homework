"""
求职公司调研 - Tavily 联网搜索工具
严格仿照 market_research_subagents：用标准库 urllib，零 SDK 依赖

⚠️ 鉴权方式说明：
Tavily 有两种 key：
  - dev tier   前缀 tvly-dev-...  免费 1000 次/月，**必须用 Authorization: Bearer header**
  - production 前缀 tvly-...      付费，header / body 两种鉴权都行

为了同时兼容两种 key，本文件统一用 Bearer header 鉴权（Tavily 官方推荐写法）。
"""
import json
import os
import urllib.request
import urllib.parse
import urllib.error
import ssl

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
TAVILY_ENDPOINT = "https://api.tavily.com/search"

_ctx = ssl.create_default_context()


def web_search(query: str, search_depth: str = "basic", max_results: int = 5,
               topic: str = "general", include_answer: bool = True) -> dict:
    """
    调用 Tavily 搜索。失败时返回 error 字符串，让上层 ReAct 能兜底重试。

    ⚠️ 鉴权用 Authorization: Bearer header（兼容 dev / production 两种 key）。
       不要把 api_key 塞进 body —— dev key 那样会报 401。
    """
    if not TAVILY_API_KEY:
        return {"error": "未设置 TAVILY_API_KEY。请先 export/set 环境变量。"}
    payload = {
        "query": query,
        "search_depth": search_depth,
        "topic": topic,
        "max_results": max_results,
        "include_answer": include_answer,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        TAVILY_ENDPOINT,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {TAVILY_API_KEY}",   # ✅ 关键：Bearer header 鉴权
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ctx) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        # 把 Tavily 返回的错误体也带出来，方便排查（比如 401 / 429）
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="ignore")[:500]
        except Exception:
            pass
        return {"error": f"Tavily HTTP {e.code}: {e.reason} | {err_body}"}
    except Exception as e:
        return {"error": f"Tavily 请求失败：{type(e).__name__}: {e}"}


def format_search_result(result: dict) -> str:
    """
    把 Tavily 返回的 dict 格式化成 ReAct Observation 用的字符串。
    """
    if "error" in result:
        return f"[搜索失败] {result['error']}"
    parts = []
    if result.get("answer"):
        parts.append(f"【搜索摘要】{result['answer']}")
    results = result.get("results") or []
    for i, r in enumerate(results[:5], 1):
        parts.append(f"[{i}] {r.get('title','')}  {r.get('url','')}\n    {r.get('content','')[:400]}")
    if not parts:
        return "[搜索无结果]"
    return "\n\n".join(parts)
