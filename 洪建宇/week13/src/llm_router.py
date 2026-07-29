"""llm_router - 大模型路由模块。

把用户的自然语言指令交给大模型，由模型从已发现的 skill 中选择一个，
并填充参数，再交给 harness 执行。

采用 OpenAI 兼容协议（/v1/chat/completions），可对接：
    - OpenAI 官方
    - 通义千问（DashScope 兼容模式）
    - DeepSeek
    - 智谱 GLM
    - Moonshot / OpenRouter 等任意 OpenAI 兼容服务

只用 Python 标准库 urllib，不引入 requests/openai 等额外依赖。
渐进式约定：本模块仅在 cli 的 chat 子命令被调用时才 import。
"""
import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, Optional


# ======================================================================
#  API 配置区 —— 请在此处填写你的大模型 API 信息（也可用环境变量覆盖）
# ======================================================================
API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"          # 你的 API Key
BASE_URL = "https://api.deepseek.com"                   # 服务地址（OpenAI 兼容）
MODEL = "deepseek-v4-flash"                                    # 模型名
TEMPERATURE = 0.2                                        # 低温度保证输出稳定
TIMEOUT = 60                                             # 请求超时（秒）
# ======================================================================
#  环境变量优先：若设置了对应环境变量，则覆盖上面的硬编码值
#  FILESKILL_API_KEY / FILESKILL_BASE_URL / FILESKILL_MODEL
# ======================================================================
API_KEY = os.environ.get("FILESKILL_API_KEY", API_KEY)
BASE_URL = os.environ.get("FILESKILL_BASE_URL", BASE_URL)
MODEL = os.environ.get("FILESKILL_MODEL", MODEL)


def _build_system_prompt(skills_meta: Dict[str, Dict[str, Any]]) -> str:
    """根据所有 skill 的元信息构造 system 提示词。"""
    skill_descs = []
    for name, meta in skills_meta.items():
        params_lines = []
        for pname, pinfo in meta.get("params", {}).items():
            req = "必填" if pinfo.get("required") else "可选"
            default = pinfo.get("default", "-")
            ptype = pinfo.get("type", "str")
            pdesc = pinfo.get("description", "")
            params_lines.append(
                f"      - {pname} ({ptype}/{req}, 默认={default}): {pdesc}"
            )
        params_text = "\n".join(params_lines) or "      （无参数）"
        skill_descs.append(
            f"  - {name}: {meta.get('description', '')}\n"
            f"    参数:\n{params_text}"
        )
    skills_block = "\n".join(skill_descs)

    return (
        "你是 FileSkill Harness 的调度助手。任务：根据用户的自然语言指令，"
        "从下方可用 skill 列表中选择最合适的一个，并填充其参数。\n\n"
        "可用 skill 列表：\n"
        f"{skills_block}\n\n"
        "规则：\n"
        "1. 只能选择列表中存在的 skill，不得臆造。\n"
        "2. 必填参数必须给出值；可选参数在用户未明确给出时使用默认值。\n"
        "3. 文件路径、文本等内容性参数直接采用用户原话中的值。\n"
        "4. 数值类参数（quality/max_width/size/start_time/end_time 等）必须是数字。\n"
        "5. 严格只输出一个 JSON 对象，不要包含任何解释文字、不要 markdown 代码块。\n\n"
        "输出格式：\n"
        '{"skill": "<skill名>", "params": {"<参数名>": <值>, ...}, '
        '"reason": "<一句话说明选择理由>"}'
    )


def call_chat_api(messages: list) -> str:
    """通用 OpenAI 兼容 /v1/chat/completions 调用，传入完整 messages 列表。

    供单轮（llm_router.route）与多轮（qa_router.answer）复用，
    保证只有一处 HTTP 实现与一处错误处理。
    """
    url = BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": MODEL,
        "temperature": TEMPERATURE,
        "messages": messages,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"大模型 API HTTP {e.code} 错误: {err_body}\n"
            f"请检查 API_KEY / BASE_URL / MODEL 配置。"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"无法连接大模型 API: {e.reason}") from e

    obj = json.loads(body)
    # OpenAI 兼容格式：choices[0].message.content
    try:
        return obj["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"大模型返回结构异常: {body}") from e


def _call_chat_api(system_prompt: str, user_input: str) -> str:
    """单轮（system + user）便捷封装，内部委托给 call_chat_api。"""
    return call_chat_api([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ])


def _extract_json(text: str) -> Dict[str, Any]:
    """从模型输出中提取 JSON 对象（兼容包裹了 markdown 代码块的情况）。"""
    text = text.strip()
    # 去掉可能的 ```json ... ``` 包裹
    if text.startswith("```"):
        text = text.strip("`")
        # 去掉开头的语言标识 json / jsonc 等
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip("`").strip()
    # 截取第一个 { 到最后一个 } 之间的内容
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"模型输出中未找到合法 JSON: {text}")
    return json.loads(text[start : end + 1])


def route(user_input: str, skills_meta: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """主入口：把用户自然语言指令路由为 {skill, params, reason}。

    skills_meta 来自 harness.list_skills()。本函数不依赖 harness 实例，
    只读元信息，保持与执行解耦。
    """
    if not skills_meta:
        raise RuntimeError("没有可用的 skill，请先检查 skills/ 目录")

    system_prompt = _build_system_prompt(skills_meta)
    raw = _call_chat_api(system_prompt, user_input)
    parsed = _extract_json(raw)

    # 基本校验
    if "skill" not in parsed:
        raise ValueError(f"模型输出缺少 skill 字段: {parsed}")
    if parsed["skill"] not in skills_meta:
        raise ValueError(
            f"模型选择了不存在的 skill: {parsed['skill']}，"
            f"可用: {list(skills_meta.keys())}"
        )
    parsed.setdefault("params", {})
    parsed.setdefault("reason", "")
    return parsed
