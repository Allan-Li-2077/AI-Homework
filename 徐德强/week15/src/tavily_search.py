"""
Tavily 联网搜索封装（零额外依赖，用标准库 urllib）

教学定位：NBA 赛前分析需要公开资料，Tavily 是为 LLM 优化的搜索 API（返回摘要 + 来源）。
用 urllib 而非 requests，避免引入新依赖（CLAUDE.md 少依赖原则）。
NBA 专用搜索会自动加入 2026-27 赛季、总决赛后的休赛期和当前日期，
并限制到 NBA 官方及主流数据来源，降低旧赛季阵容污染。

使用方式：
  from tavily_search import nba_search
  r = nba_search("詹姆斯签约76人 杰伦布朗交易至76人 保罗乔治离开76人 湖人最新阵容")
  # r = {"answer": "...", "results": [{"title","url","content"}], "response_time": ...}

依赖：环境变量 TAVILY_API_KEY
"""
import os, json, urllib.request, logging
from datetime import date, datetime
logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
OFFSEASON_START_DATE = "2026-06-01"
NBA_DOMAINS = [
    "nba.com",
    "espn.com",
    "basketball-reference.com",
    "spotrac.com",
    "news.hupu.com",
    "voice.hupu.com",
    "bbs.hupu.com",
]


def tavily_search(
    query: str,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    topic: str = "general",
    search_depth: str = "basic",
    start_date: str | None = None,
    end_date: str | None = None,
    include_raw_content: str | bool = False,
) -> dict:
    """调用 Tavily 搜索。返回 {answer, results, response_time}。
    失败返回 {"error": ...}，不抛异常（ReAct loop 兜底）。"""
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return {"error": "未设置 TAVILY_API_KEY"}
    payload = {
        "api_key": key,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "topic": topic,
        "include_answer": True,
    }
    if search_depth == "advanced":
        payload["chunks_per_source"] = 3
    if include_domains:
        payload["include_domains"] = include_domains
    if start_date:
        payload["start_date"] = start_date
    if end_date:
        payload["end_date"] = end_date
    if include_raw_content:
        payload["include_raw_content"] = include_raw_content
    try:
        req = urllib.request.Request(
            TAVILY_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # 精简结果，只留对 LLM 有用的字段
        results = []
        for item in data.get("results", []):
            title = item.get("title", "")
            url = item.get("url", "")
            content = item.get("content") or ""
            is_hupu_news = (
                "[流言板]" in title
                and ("由虎扑篮球资讯 发表" in content or "虎扑篮球资讯(" in content)
            )
            if "bbs.hupu.com" in url and not is_hupu_news:
                continue
            results.append({
                "title": title,
                "url": url,
                "published_date": item.get("published_date", ""),
                "content": content[:600],
            })
        results.sort(key=lambda item: _date_key(item.get("published_date", "")), reverse=True)
        return {"answer": data.get("answer") or "",
                "results": results,
                "response_time": data.get("response_time")}
    except Exception as e:
        logger.warning(f"Tavily 搜索失败 '{query}': {e}")
        return {"error": f"{type(e).__name__}: {str(e)[:100]}"}


def _date_key(value: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=None)
        except ValueError:
            pass
    return datetime.min


def nba_search(query: str, max_results: int = 6) -> dict:
    """搜索当前 NBA 资料，优先使用官方和主流数据来源。"""
    enriched_query = (
        f"{query} 2026-27 NBA current roster latest transactions "
        f"after 2026 NBA Finals as of {date.today().isoformat()} "
        f"虎扑资讯 虎扑新闻 官方消息 官宣 已确定 休赛期 阵容"
    )
    return tavily_search(
        enriched_query,
        max_results=max_results,
        include_domains=NBA_DOMAINS,
        topic="news",
        search_depth="advanced",
        start_date=OFFSEASON_START_DATE,
        end_date=date.today().isoformat(),
        include_raw_content="markdown",
    )


def format_search_result(r: dict) -> str:
    """把 Tavily 返回格式化成喂给 LLM 的文本。"""
    if "error" in r:
        return f"搜索失败: {r['error']}"
    parts = []
    parts.append("注意：只能把搜索结果中有明确来源支持的球员写入已核验阵容；没有来源支持时写无法核验。")
    if r.get("answer"):
        parts.append(f"摘要: {r['answer']}")
    for i, res in enumerate(r.get("results", []), 1):
        published = f" | 日期: {res['published_date']}" if res.get("published_date") else ""
        parts.append(
            f"[{i}] {res['title']}{published}\n"
            f"    来源: {res['url']}\n"
            f"    {res['content'][:400]}"
        )
    return "\n".join(parts) if parts else "无结果"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = nba_search("詹姆斯签约76人 杰伦布朗交易至76人 保罗乔治离开76人 湖人最新阵容")
    print(format_search_result(r)[:400])
