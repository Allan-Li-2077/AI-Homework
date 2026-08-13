"""极简 LLM 客户端（DeepSeek，OpenAI 兼容接口）
依赖：pip install openai
环境变量：DEEPSEEK_API_KEY
"""
import os, time, logging
from openai import OpenAI

logger = logging.getLogger(__name__)
DEEPSEEK_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

_client = None  # 单例：客户端只创建一次

def get_client():
    global _client
    if _client is None:
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            raise EnvironmentError("请设置 DEEPSEEK_API_KEY")
        _client = OpenAI(api_key=key, base_url=DEEPSEEK_URL)
    return _client

def llm_chat(system, user, *, temperature=0.0, max_tokens=1024, stop=None,
             retries=3, json_mode=False):
    """单轮 LLM 对话。
    json_mode=True 时强制输出合法 JSON（response_format 约束）。"""
    if json_mode:
        kwargs = {"response_format": {"type": "json_object"}}
        stop = None  # JSON 模式靠 } 天然截断，不需要 stop，且两者同时传会冲突
    for attempt in range(retries):
        try:
            resp = get_client().chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=temperature, max_tokens=max_tokens,
                stop=stop, **kwargs)
            return resp.choices[0].message.content
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
            logger.warning(f"LLM 重试({attempt + 1}): {str(e)[:80]}")