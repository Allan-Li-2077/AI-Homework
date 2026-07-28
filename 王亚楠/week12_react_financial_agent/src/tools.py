"""
5个工具的统一实现，供 ReAct Agent 调用

教学重点：
  1. 工具异构性：语义检索 / 结构化数据 / 实时行情 / 计算 / 静态映射
  2. 每个工具返回统一格式的字符串，便于 LLM 消费
  3. 所有网络请求做异常保护，降级返回错误描述而非抛出

使用方式：
  from tools import TOOLS_MAP
  result = TOOLS_MAP["rag_search"](query="茅台2023年营收")

注意：
  rag_search 使用 DashScope text-embedding-v3（1024维）与建索引时保持一致，
  需要设置 DASHSCOPE_API_KEY 环境变量。
"""

import os
import json
import math
import logging
from pathlib import Path
from typing import Any

import numpy as np
import faiss
from openai import OpenAI

logger = logging.getLogger(__name__)

# ── 记忆存储注入 ──────────────────────────────────────────────────────────────
_memory_store = None

def set_memory_store(store):
    """注入 MemoryStore 实例，供记忆工具使用"""
    global _memory_store
    _memory_store = store

def get_memory_store():
    """获取当前 MemoryStore 实例（懒初始化）"""
    global _memory_store
    if _memory_store is None:
        from memory import MemoryStore
        _memory_store = MemoryStore()
    return _memory_store

# ── 路径配置 ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
VECTORSTORE_DIR = BASE_DIR / "vectorstore"

# ── DashScope Embedding 客户端（与建索引时相同的模型）──────────────────────────
_embed_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
EMBED_MODEL = "text-embedding-v3"

# ── 公司映射（名称 → 股票代码） ────────────────────────────────────────────────
COMPANY_MAP = {
    "贵州茅台": "600519",
    "茅台":     "600519",
    "五粮液":   "000858",
    "宁德时代": "300750",
    "中国平安": "601318",
    "平安":     "601318",
    "海康威视": "002415",
    "海康":     "002415",
}

# ── RAG 工具（懒加载，首次调用时初始化索引） ─────────────────────────────────
_faiss_index = None
_faiss_meta  = None

def _load_rag():
    global _faiss_index, _faiss_meta
    if _faiss_index is not None:
        return
    logger.info("加载 FAISS 索引...")
    _faiss_index = faiss.read_index(str(VECTORSTORE_DIR / "faiss_index.bin"))
    with open(VECTORSTORE_DIR / "faiss_meta.json", encoding="utf-8") as f:
        _faiss_meta = json.load(f)
    logger.info(f"FAISS 就绪，共 {_faiss_index.ntotal} 条向量")


def _embed_query(text: str) -> np.ndarray:
    """调用 DashScope text-embedding-v3 对查询文本编码（与建索引时保持一致）"""
    resp = _embed_client.embeddings.create(model=EMBED_MODEL, input=[text])
    vec  = np.array(resp.data[0].embedding, dtype="float32")
    vec  = vec / np.linalg.norm(vec)   # 归一化，与建索引时一致
    return vec.reshape(1, -1)


def tool_rag_search(query: str, top_k: int = 5) -> str:
    """在年报 FAISS 索引中语义检索，返回最相关的文本段落"""
    try:
        _load_rag()
        vec = _embed_query(query)
        scores, indices = _faiss_index.search(vec, top_k)
        results = []
        for rank, (score, idx) in enumerate(zip(scores[0], indices[0]), 1):
            if idx < 0:
                continue
            meta = _faiss_meta[idx]
            results.append(
                f"[{rank}] 来源：{meta.get('stock_code','')} {meta.get('year','')}年报 "
                f"第{meta.get('page_num','')}页 (相关度:{score:.3f})\n{meta['content']}"
            )
        return "\n\n".join(results) if results else "未检索到相关内容"
    except Exception as e:
        return f"rag_search 执行出错: {e}"


# ── 公司映射工具 ──────────────────────────────────────────────────────────────

def tool_company_lookup(name: str) -> str:
    """将公司中文名转换为 A 股股票代码"""
    code = COMPANY_MAP.get(name.strip())
    if code:
        return f"{name} 的股票代码为 {code}"
    candidates = [k for k in COMPANY_MAP if name in k]
    if candidates:
        return "未精确匹配，相似公司：" + "、".join(f"{k}({COMPANY_MAP[k]})" for k in candidates)
    supported = "、".join(COMPANY_MAP.keys())
    return f"未找到 '{name}'，当前支持：{supported}"


# ── 计算器工具 ────────────────────────────────────────────────────────────────

_SAFE_NAMES = {k: v for k, v in math.__dict__.items() if not k.startswith("_")}
_SAFE_NAMES.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})

def tool_calculator(expr: str) -> str:
    """安全计算数学表达式，支持四则运算和 math 模块函数"""
    try:
        result = eval(expr, {"__builtins__": {}}, _SAFE_NAMES)  # noqa: S307
        return str(round(float(result), 6))
    except Exception as e:
        return f"计算出错: {e}，表达式: {expr}"


# ── AkShare：实时财务指标 ─────────────────────────────────────────────────────

def tool_financial_indicator(symbol: str) -> str:
    """获取 A 股近3年关键财务指标：营收/净利润/毛利率/ROE/资产负债率等"""
    try:
        import akshare as ak
        df = ak.stock_financial_abstract(symbol=symbol)
        if df is None or df.empty:
            return f"未获取到 {symbol} 的财务指标数据"

        # 取最近3个年报期（列名格式 YYYYMMDD，筛选 1231 结尾的年报）
        date_cols = [c for c in df.columns if str(c).endswith("1231")][:3]
        if not date_cols:
            date_cols = df.columns[2:5].tolist()

        # 感兴趣的指标行名
        target_rows = ["归母净利润", "营业总收入", "毛利率", "净利率",
                       "净资产收益率", "资产负债率", "每股收益"]
        lines = [f"股票代码: {symbol}，数据截至最近三个年报"]
        for _, row in df.iterrows():
            label = str(row.get("指标", ""))
            if any(t in label for t in target_rows):
                vals = []
                for col in date_cols:
                    v = row.get(col)
                    try:
                        v = f"{float(v):.4g}"
                    except (TypeError, ValueError):
                        v = str(v)
                    vals.append(f"{col[:4]}年: {v}")
                lines.append(f"  {label}: " + " | ".join(vals))

        return "\n".join(lines) if len(lines) > 1 else f"{symbol} 未找到关键财务指标行"
    except Exception as e:
        return f"financial_indicator 执行出错: {e}"


# ── AkShare：历史股价 ─────────────────────────────────────────────────────────

def tool_stock_price(symbol: str, start_date: str, end_date: str) -> str:
    """
    获取 A 股历史股价及区间涨跌幅
    日期格式：YYYYMMDD，例如 20230101
    """
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        if df is None or df.empty:
            return f"未获取到 {symbol} 在 {start_date}~{end_date} 的行情数据"

        first_close = float(df.iloc[0]["收盘"])
        last_close  = float(df.iloc[-1]["收盘"])
        high        = float(df["最高"].max())
        low         = float(df["最低"].min())
        change_pct  = (last_close - first_close) / first_close * 100

        return (
            f"股票代码: {symbol}，区间: {start_date}~{end_date}\n"
            f"  区间起始收盘价: {first_close:.2f} 元\n"
            f"  区间末尾收盘价: {last_close:.2f} 元\n"
            f"  区间最高价: {high:.2f} 元\n"
            f"  区间最低价: {low:.2f} 元\n"
            f"  区间涨跌幅: {change_pct:+.2f}%"
        )
    except Exception as e:
        return f"stock_price 执行出错: {e}"


# ── 记忆工具 ──────────────────────────────────────────────────────────────────

def tool_memory_search(query: str) -> str:
    """在记忆库中搜索相关的历史对话和已存储的事实"""
    try:
        store = get_memory_store()
        # 搜索事实
        fact_results = store.search_facts(query)
        # 搜索最近对话
        recent = store.load_recent(n=5)

        lines = []
        if fact_results:
            lines.append("## 记忆中的相关事实")
            for r in fact_results:
                lines.append(f"- {r['key']}: {r['value']} (来源: {r.get('source', '')})")

        if recent:
            # 简单关键词过滤
            matched = [t for t in recent if query.lower() in t["question"].lower()
                       or any(query.lower() in str(a).lower() for a in t.get("tools_used", []))]
            if matched:
                lines.append("## 相关历史对话")
                for t in matched[-3:]:
                    lines.append(f"- [{t['timestamp'][:10]}] 问: {t['question']}")
                    lines.append(f"  答: {t['answer'][:150]}")

        return "\n".join(lines) if lines else f"未在记忆中找到与 '{query}' 相关的信息"
    except Exception as e:
        return f"memory_search 执行出错: {e}"


def tool_memory_save(key: str, content: str) -> str:
    """主动保存重要信息到记忆库，供后续查询复用"""
    try:
        store = get_memory_store()
        store.add_fact(key, content, source="agent-saved")
        return f"已记住: {key} = {content}"
    except Exception as e:
        return f"memory_save 执行出错: {e}"

# ── 统一工具注册表 ─────────────────────────────────────────────────────────────

TOOLS_MAP: dict[str, Any] = {
    "rag_search":          tool_rag_search,
    "company_lookup":      tool_company_lookup,
    "calculator":          tool_calculator,
    "financial_indicator": tool_financial_indicator,
    "stock_price":         tool_stock_price,
    "memory_search":       tool_memory_search,
    "memory_save":         tool_memory_save,
}

# Function Calling 版所需的 JSON Schema 描述
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": "在5家A股公司（贵州茅台/五粮液/宁德时代/中国平安/海康威视）2021-2023年年报中语义检索，适合查询定性描述、战略规划、风险因素、管理层讨论等文本内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题，尽量具体，如'茅台2023年毛利率'"},
                    "top_k": {"type": "integer", "description": "返回结果数量，默认5", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "company_lookup",
            "description": "将公司中文名称转换为A股股票代码，在调用 financial_indicator 或 stock_price 前必须先用此工具获取代码",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "公司中文名，如'贵州茅台'"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "安全计算数学表达式，支持加减乘除、幂运算、math模块函数（sqrt/log/pow等），用于财务计算如增长率、PE、差值等",
            "parameters": {
                "type": "object",
                "properties": {
                    "expr": {"type": "string", "description": "数学表达式，如 '(747 - 524) / 524 * 100'"},
                },
                "required": ["expr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "financial_indicator",
            "description": "获取A股近3年关键财务指标（营收/净利润/毛利率/ROE/资产负债率等），适合做跨年对比或与年报数据交叉验证",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码，如'600519'"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stock_price",
            "description": "获取A股历史股价及区间涨跌幅，日期格式为YYYYMMDD",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol":     {"type": "string", "description": "股票代码，如'600519'"},
                    "start_date": {"type": "string", "description": "起始日期，格式YYYYMMDD，如'20230101'"},
                    "end_date":   {"type": "string", "description": "结束日期，格式YYYYMMDD，如'20231231'"},
                },
                "required": ["symbol", "start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "在记忆库中搜索历史对话和已存储的财务事实，用于复用之前的分析结果、查找已知的股票代码或财务数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，如'茅台'、'毛利率'、'股票代码'"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_save",
            "description": "将重要信息主动保存到记忆库，供后续查询复用。适合保存股票代码映射、关键财务数据、分析结论等",
            "parameters": {
                "type": "object",
                "properties": {
                    "key":   {"type": "string", "description": "信息的简短标识，如'股票代码:茅台'"},
                    "content": {"type": "string", "description": "要保存的内容，如'600519'"},
                },
                "required": ["key", "content"],
            },
        },
    },
]
