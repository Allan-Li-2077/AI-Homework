"""
极简 LLM 客户端
使用 DeepSeek API（OpenAI 兼容接口）
"""
import os
import time
import logging

logger = logging.getLogger(__name__)

# 默认配置
DEEPSEEK_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

_client = None


def get_client():
    """获取 OpenAI 客户端（单例）"""
    global _client
    if _client is None:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请先安装 openai: pip install openai")
        
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            raise EnvironmentError("请设置环境变量 DEEPSEEK_API_KEY")
        
        _client = OpenAI(api_key=key, base_url=DEEPSEEK_URL)
    return _client


def llm_chat(system, user, *, temperature=0.0, max_tokens=1024, stop=None, retries=3):
    """
    单轮 LLM 对话
    
    Args:
        system: 系统提示词
        user: 用户输入
        temperature: 温度参数
        max_tokens: 最大生成 token 数
        stop: 停止词列表（ReAct 在 Observation 前截断用）
        retries: 重试次数
    
    Returns:
        LLM 生成的文本
    """
    for attempt in range(retries):
        try:
            resp = get_client().chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop
            )
            return resp.choices[0].message.content
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
            logger.warning(f"LLM 重试({attempt + 1}): {str(e)[:80]}")
