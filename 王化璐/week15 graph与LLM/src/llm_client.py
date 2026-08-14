"""
求职公司调研 - DeepSeek LLM 客户端
严格仿照 market_research_subagents 项目的极简风格
"""
from openai import OpenAI
import os

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

_client = None


def get_client():
    global _client
    if _client is None:
        if not DEEPSEEK_API_KEY:
            raise RuntimeError(
                "未设置 DEEPSEEK_API_KEY。\n"
                "Windows PowerShell: $env:DEEPSEEK_API_KEY='sk-xxxx'\n"
                "Windows CMD:      set DEEPSEEK_API_KEY=sk-xxxx"
            )
        _client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return _client


def chat(messages, temperature=0.2, max_tokens=4096, stop=None, stream=False):
    """
    统一的聊天接口。stream=True 时返回迭代器（逐 token）。
    """
    kwargs = dict(
        model=DEEPSEEK_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if stop:
        kwargs["stop"] = stop
    if stream:
        def gen():
            for chunk in get_client().chat.completions.create(stream=True, **kwargs):
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
        return gen()
    else:
        resp = get_client().chat.completions.create(stream=False, **kwargs)
        return resp.choices[0].message.content


def chat_structured_json(messages, temperature=0.1, max_tokens=4096):
    """强行要 JSON 输出的调用——返回 dict"""
    import json
    messages = list(messages) + [
        {"role": "user", "content": "请严格按以上要求，只输出合法 JSON。不要加任何解释、前言、Markdown 代码块。直接输出 { ... }。"}
    ]
    raw = chat(messages, temperature=temperature, max_tokens=max_tokens)
    # 粗暴兜底：有时候 LLM 还是包了 ```json ... ```
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    # 再兜底：去掉 JSON 首尾以外的噪声字符
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end+1]
    try:
        return json.loads(raw)
    except Exception as e:
        raise ValueError(f"LLM 输出不是合法 JSON：{e}\nRAW: {raw[:500]}")
