"""
5个工具的统一实现，供 ReAct Agent 调用

教学重点：
  1. 工具异构性：语义检索 / 概念映射 / 计算 / 论文摘要 / 概念解释
  2. 每个工具返回统一格式的字符串，便于 LLM 消费
  3. 所有网络请求做异常保护，降级返回错误描述而非抛出

使用方式：
  from tools import TOOLS_MAP
  result = TOOLS_MAP["rag_search"](query="Transformer注意力机制")

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

# ── 路径配置 ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
VECTORSTORE_DIR = BASE_DIR / "vectorstore"

# ── DashScope Embedding 客户端（与建索引时相同的模型）──────────────────────────
_embed_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
EMBED_MODEL = "text-embedding-v3"

# ── AI 主题/概念映射（名称 → 关键信息） ────────────────────────────────────────
AI_CONCEPT_MAP = {
    "transformer": {
        "name": "Transformer",
        "type": "架构",
        "year": "2017",
        "description": "基于注意力机制的序列建模架构，由Google提出，替代RNN/CNN",
        "key_points": ["自注意力机制", "多头注意力", "位置编码", "Encoder-Decoder结构"],
    },
    "attention": {
        "name": "注意力机制",
        "type": "机制",
        "year": "2014",
        "description": "让模型在处理序列时能够聚焦于重要部分的机制",
        "key_points": ["缩放点积注意力", "多头注意力", "自注意力", "交叉注意力"],
    },
    "bert": {
        "name": "BERT",
        "type": "模型",
        "year": "2018",
        "description": "双向Transformer预训练模型，由Google提出",
        "key_points": ["Masked Language Model", "Next Sentence Prediction", "预训练+微调"],
    },
    "gpt": {
        "name": "GPT",
        "type": "模型",
        "year": "2018",
        "description": "生成式预训练Transformer，由OpenAI提出",
        "key_points": ["自回归语言模型", "Decoder-only结构", "GPT-1/2/3/4系列"],
    },
    "rnn": {
        "name": "RNN",
        "type": "架构",
        "year": "1982",
        "description": "循环神经网络，处理序列数据的经典架构",
        "key_points": ["循环连接", "梯度消失/爆炸", "LSTM/GRU变体"],
    },
    "lstm": {
        "name": "LSTM",
        "type": "模型",
        "year": "1997",
        "description": "长短期记忆网络，RNN的改进变体",
        "key_points": ["门控机制", "遗忘门", "输入门", "输出门", "细胞状态"],
    },
    "cnn": {
        "name": "CNN",
        "type": "架构",
        "year": "1998",
        "description": "卷积神经网络，主要用于计算机视觉",
        "key_points": ["卷积层", "池化层", "局部感受野", "参数共享"],
    },
    "embedding": {
        "name": "词嵌入",
        "type": "技术",
        "year": "2013",
        "description": "将单词映射到低维稠密向量空间",
        "key_points": ["Word2Vec", "GloVe", "FastText", "BERT Embedding"],
    },
    "fine-tuning": {
        "name": "微调",
        "type": "技术",
        "year": "-",
        "description": "在预训练模型基础上用下游任务数据训练",
        "key_points": ["冻结/解冻层", "学习率调整", "LoRA", "Adapter"],
    },
    "prompt": {
        "name": "提示词工程",
        "type": "技术",
        "year": "-",
        "description": "设计有效提示词引导模型输出",
        "key_points": ["指令跟随", "思维链", "少样本学习", "提示词模板"],
    },
    "diffusion": {
        "name": "扩散模型",
        "type": "模型",
        "year": "2015",
        "description": "通过逐步去噪生成数据的生成模型",
        "key_points": ["前向扩散过程", "逆向去噪过程", "DDPM", "Stable Diffusion"],
    },
    "reinforcement": {
        "name": "强化学习",
        "type": "方法",
        "year": "-",
        "description": "通过奖励机制训练智能体",
        "key_points": ["策略梯度", "Q-learning", "Actor-Critic", "PPO"],
    },
}

import shutil
import tempfile

_faiss_index = None
_faiss_meta = None

def _has_non_ascii(path: str) -> bool:
    return any(ord(ch) > 127 for ch in str(path))

def _load_rag():
    global _faiss_index, _faiss_meta
    if _faiss_index is not None:
        return
    logger.info("加载 FAISS 索引...")
    src_index = VECTORSTORE_DIR / "faiss_index.bin"
    src_meta = VECTORSTORE_DIR / "faiss_meta.json"
    
    if os.name == "nt" and _has_non_ascii(src_index):
        tmpdir = tempfile.mkdtemp()
        tmp_index = os.path.join(tmpdir, "faiss_index.bin")
        shutil.copy2(str(src_index), tmp_index)
        _faiss_index = faiss.read_index(tmp_index)
    else:
        _faiss_index = faiss.read_index(str(src_index))
    
    with open(src_meta, encoding="utf-8") as f:
        _faiss_meta = json.load(f)
    logger.info(f"FAISS 就绪，共 {_faiss_index.ntotal} 条向量")


def _embed_query(text: str) -> np.ndarray:
    """调用 DashScope text-embedding-v3 对查询文本编码（与建索引时保持一致）"""
    resp = _embed_client.embeddings.create(model=EMBED_MODEL, input=[text])
    vec  = np.array(resp.data[0].embedding, dtype="float32")
    vec  = vec / np.linalg.norm(vec)
    return vec.reshape(1, -1)


def tool_rag_search(query: str, top_k: int = 5) -> str:
    """在 AI 论文 FAISS 索引中语义检索，返回最相关的文本段落"""
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
                f"[{rank}] 来源：{meta.get('title','')} ({meta.get('year','')}) "
                f"第{meta.get('page_num','')}页 (相关度:{score:.3f})\n"
                f"主题: {meta.get('topic','')}\n{meta['content']}"
            )
        return "\n\n".join(results) if results else "未检索到相关内容"
    except Exception as e:
        return f"rag_search 执行出错: {e}"


# ── AI 概念映射工具 ──────────────────────────────────────────────────────────

def tool_ai_concept_lookup(name: str) -> str:
    """查询 AI 概念的基本信息（架构/模型/技术）"""
    name_lower = name.strip().lower()
    concept = AI_CONCEPT_MAP.get(name_lower)
    if concept:
        key_points = "、".join(concept["key_points"])
        return (
            f"概念: {concept['name']}\n"
            f"类型: {concept['type']}\n"
            f"年份: {concept['year']}\n"
            f"描述: {concept['description']}\n"
            f"关键点: {key_points}"
        )
    candidates = [k for k in AI_CONCEPT_MAP if name_lower in k or k in name_lower]
    if candidates:
        return "未精确匹配，相似概念：" + "、".join(f"{AI_CONCEPT_MAP[k]['name']}" for k in candidates)
    supported = "、".join(AI_CONCEPT_MAP[k]["name"] for k in AI_CONCEPT_MAP)
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


# ── 论文摘要工具 ─────────────────────────────────────────────────────────────

def tool_paper_summary(title: str) -> str:
    """检索论文的摘要信息"""
    try:
        _load_rag()
        query = f"{title} 摘要"
        vec = _embed_query(query)
        scores, indices = _faiss_index.search(vec, 3)
        results = []
        for rank, (score, idx) in enumerate(zip(scores[0], indices[0]), 1):
            if idx < 0:
                continue
            meta = _faiss_meta[idx]
            if meta.get("section") in ["Abstract", "摘要"] or "abstract" in str(meta.get("section", "")).lower():
                results.append(
                    f"[{rank}] 论文: {meta.get('title','')} ({meta.get('year','')})\n"
                    f"内容: {meta['content'][:500]}"
                )
        if results:
            return "\n\n".join(results)
        
        for idx in indices[0]:
            if idx < 0:
                continue
            meta = _faiss_meta[idx]
            if title.lower() in meta.get("title", "").lower():
                return f"论文: {meta.get('title','')} ({meta.get('year','')})\n主题: {meta.get('topic','')}\n内容预览: {meta['content'][:500]}"
        
        return f"未找到 '{title}' 的论文信息"
    except Exception as e:
        return f"paper_summary 执行出错: {e}"


# ── 概念对比工具 ─────────────────────────────────────────────────────────────

def tool_concept_compare(concept1: str, concept2: str) -> str:
    """对比两个 AI 概念的异同"""
    concept1_lower = concept1.strip().lower()
    concept2_lower = concept2.strip().lower()
    
    c1 = AI_CONCEPT_MAP.get(concept1_lower)
    c2 = AI_CONCEPT_MAP.get(concept2_lower)
    
    result = []
    
    if c1 and c2:
        result.append(f"【{c1['name']}】")
        result.append(f"  类型: {c1['type']} | 年份: {c1['year']}")
        result.append(f"  描述: {c1['description']}")
        result.append(f"  关键点: {'、'.join(c1['key_points'])}")
        result.append("")
        result.append(f"【{c2['name']}】")
        result.append(f"  类型: {c2['type']} | 年份: {c2['year']}")
        result.append(f"  描述: {c2['description']}")
        result.append(f"  关键点: {'、'.join(c2['key_points'])}")
        result.append("")
        result.append("【对比分析】")
        
        if c1["type"] == c2["type"]:
            result.append("  ✓ 同类型概念")
        else:
            result.append(f"  ✗ 类型不同：{c1['type']} vs {c2['type']}")
        
        if c1["year"] == c2["year"]:
            result.append("  ✓ 同年提出")
        else:
            result.append(f"  ✗ 年份不同：{c1['year']} vs {c2['year']}")
        
        common_points = set(c1["key_points"]) & set(c2["key_points"])
        if common_points:
            result.append(f"  共同关键点: {'、'.join(common_points)}")
        
        diff_points = set(c1["key_points"]) ^ set(c2["key_points"])
        if diff_points:
            result.append(f"  差异关键点: {'、'.join(diff_points)}")
    
    elif c1:
        result.append(f"找到【{c1['name']}】的信息，但未找到【{concept2}】")
    elif c2:
        result.append(f"找到【{c2['name']}】的信息，但未找到【{concept1}】")
    else:
        result.append(f"两个概念均未找到：【{concept1}】、【{concept2}】")
    
    return "\n".join(result)


# ── 统一工具注册表 ─────────────────────────────────────────────────────────────

TOOLS_MAP: dict[str, Any] = {
    "rag_search":          tool_rag_search,
    "ai_concept_lookup":   tool_ai_concept_lookup,
    "calculator":          tool_calculator,
    "paper_summary":       tool_paper_summary,
    "concept_compare":     tool_concept_compare,
}

# Function Calling 版所需的 JSON Schema 描述
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": "在AI技术论文库中语义检索，适合查询论文中的具体内容、算法细节、实验结果、技术原理等",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问题，尽量具体，如'Transformer注意力机制原理'"},
                    "top_k": {"type": "integer", "description": "返回结果数量，默认5", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ai_concept_lookup",
            "description": "查询AI概念的基本信息（包括架构、模型、技术等），如Transformer、BERT、GPT、RNN、LSTM等",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "概念名称，如'Transformer'"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "安全计算数学表达式，支持加减乘除、幂运算、math模块函数（sqrt/log/pow等），用于计算如模型参数数量、复杂度等",
            "parameters": {
                "type": "object",
                "properties": {
                    "expr": {"type": "string", "description": "数学表达式，如'(512 * 512) * 6'"},
                },
                "required": ["expr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "paper_summary",
            "description": "检索论文的摘要信息，获取论文的核心内容和贡献",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "论文标题，如'Attention Is All You Need'"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "concept_compare",
            "description": "对比两个AI概念的异同，包括类型、年份、描述、关键点等",
            "parameters": {
                "type": "object",
                "properties": {
                    "concept1": {"type": "string", "description": "第一个概念名称，如'Transformer'"},
                    "concept2": {"type": "string", "description": "第二个概念名称，如'RNN'"},
                },
                "required": ["concept1", "concept2"],
            },
        },
    },
]