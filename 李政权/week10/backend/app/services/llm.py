from openai import OpenAI

from app.config import settings


def _use_mock() -> bool:
    return not settings.has_deepseek()


def get_deepseek_client() -> OpenAI:
    return OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )


def chat(
    messages: list[dict],
    temperature: float = 0.3,
    stream: bool = False,
):
    if _use_mock():
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")
    client = get_deepseek_client()
    return client.chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        temperature=temperature,
        stream=stream,
    )


def chat_text(messages: list[dict], temperature: float = 0.3) -> str:
    if _use_mock():
        # 离线兜底：便于未配密钥时仍可演示 RAG 检索链路
        system = messages[0].get("content", "") if messages else ""
        if "意图分类器" in system:
            raise RuntimeError("mock intent")
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if "参考资料" in user:
            return (
                "【离线演示模式：未配置 DeepSeek API Key】\n"
                "已根据本地知识库检索到相关年报片段，请在 .env 中配置 DEEPSEEK_API_KEY 后获得完整生成回答。\n"
                "检索到的资料摘要见下方引用。"
            )
        return (
            "【离线演示模式】当前未配置 DeepSeek API Key。"
            "通用问答需要大模型；年报类问题可先体验本地检索。"
            "请复制 .env.example 为 .env 并填写密钥。"
        )
    resp = chat(messages, temperature=temperature, stream=False)
    return (resp.choices[0].message.content or "").strip()
