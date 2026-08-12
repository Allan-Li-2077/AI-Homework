"""
极简 LLM 客户端（代码审查 subagent 项目用）

支持 DeepSeek（OpenAI 兼容接口）和 Anthropic Claude。
默认使用 DeepSeek deepseek-chat，设置 ANTHROPIC_API_KEY 可切换 Claude。

依赖：pip install openai anthropic
"""

import os
import time
import logging

logger = logging.getLogger(__name__)

DEEPSEEK_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

_client = None
_client_type = None  # "deepseek" | "anthropic"


def get_client():
    """获取 LLM 客户端，优先 Anthropic（如有 key），否则 DeepSeek。"""
    global _client, _client_type

    if _client is not None:
        return _client, _client_type

    # 优先 Anthropic
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            from anthropic import Anthropic
            _client = Anthropic(api_key=anthropic_key)
            _client_type = "anthropic"
            logger.info("使用 Anthropic Claude 模型")
            return _client, _client_type
        except ImportError:
            logger.warning("anthropic 未安装，回退 DeepSeek")

    # 回退 DeepSeek
    from openai import OpenAI
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise EnvironmentError("请设置 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY")
    _client = OpenAI(api_key=key, base_url=DEEPSEEK_URL)
    _client_type = "deepseek"
    return _client, _client_type


def llm_chat(system: str, user: str, *,
             temperature: float = 0.0,
             max_tokens: int = 1024,
             stop: list = None,
             retries: int = 3) -> str:
    """单轮 LLM 对话。stop 用于 ReAct 在 Observation 前截断。"""
    client, ctype = get_client()

    for attempt in range(retries):
        try:
            if ctype == "anthropic":
                import anthropic
                messages = []
                if system:
                    messages.append({"role": "user", "content": user})
                else:
                    messages.append({"role": "user", "content": user})

                kwargs = dict(
                    model="claude-sonnet-5-20251001",
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system if system else anthropic.NOT_GIVEN,
                    messages=[{"role": "user", "content": user}],
                )
                if stop:
                    kwargs["stop_sequences"] = stop
                resp = client.messages.create(**kwargs)
                # Claude 返回 content 列表，取第一个 text block
                for block in resp.content:
                    if hasattr(block, "text"):
                        return block.text
                return resp.content[0].text if resp.content else ""

            else:
                # DeepSeek (OpenAI compatible)
                resp = client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stop=stop,
                )
                return resp.choices[0].message.content

        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
            logger.warning(f"LLM 重试({attempt + 1}): {str(e)[:80]}")
