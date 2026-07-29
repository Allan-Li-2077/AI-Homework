"""qa_router - 问答式工具调用路由（ReAct 多轮循环）。

与 llm_router.route() 的「单轮路由」不同，本模块实现多轮 ReAct 循环：

    用户提问
      -> 大模型思考
      -> 调用 tool（某个 skill）
      -> 把工具结果作为观察反馈给模型
      -> 模型再思考，可继续调用其它工具
      -> ... 直到模型产出 final_answer

大模型每轮严格输出一个 JSON 对象，二选一：
    {"action": "call_tool",    "thought": "...", "tool": "...", "params": {...}}
    {"action": "final_answer", "thought": "...", "answer": "..."}

终止条件：
    - 模型输出 final_answer
    - 达到 max_iterations（防止死循环）
    - 工具执行错误会作为「观察」反馈给模型，让其恢复或改换工具，
      而不是直接崩溃——这提升了问答的鲁棒性。

复用 llm_router 中的 API 配置与 call_chat_api，无重复 HTTP 代码。
"""
import json
from typing import Any, Callable, Dict, List, Optional

from llm_router import call_chat_api


def _build_qa_system_prompt(skills_meta: Dict[str, Dict[str, Any]]) -> str:
    """构造 ReAct 系统提示词：描述可用工具 + 输出协议。"""
    tool_descs: List[str] = []
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
        tool_descs.append(
            f"  - {name}: {meta.get('description', '')}\n"
            f"    参数:\n{params_text}"
        )
    tools_block = "\n".join(tool_descs)

    return (
        "你是 FileSkill Harness 的问答助手，具备「思考 + 调用工具 + 观察」的 ReAct 能力。\n"
        "面对用户的问题，你需要：\n"
        "1. 先思考问题需要哪些信息或操作；\n"
        "2. 若需要调用工具（skill），输出 call_tool 动作；\n"
        "3. 根据工具返回的观察结果继续思考，可多次调用不同工具；\n"
        "4. 收集到足够信息后，输出 final_answer 给出最终回答。\n\n"
        f"可用工具（skill）列表：\n{tools_block}\n\n"
        "规则：\n"
        "- 只能调用列表中存在的工具，不得臆造。\n"
        "- 必填参数必须给出值；可选参数未明确时用默认值。\n"
        "- 数值参数必须是数字。\n"
        "- 如果某工具因缺少依赖或参数错误而失败，观察结果会告诉你原因，"
        "你可以换工具、修正参数，或直接给出说明性回答。\n"
        "- 严格只输出一个 JSON 对象，不要 markdown 代码块、不要多余解释。\n\n"
        "输出格式二选一：\n"
        '调用工具: {"action": "call_tool", "thought": "<简短思考>", '
        '"tool": "<工具名>", "params": {...}}\n'
        '最终回答: {"action": "final_answer", "thought": "<简短思考>", '
        '"answer": "<给用户的最终回答>"}'
    )


def _extract_json(text: str) -> Dict[str, Any]:
    """从模型输出提取 JSON 对象（兼容 markdown 代码块包裹）。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip("`").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"模型输出中未找到合法 JSON: {text}")
    return json.loads(text[start : end + 1])


def _execute_tool(harness, tool: str, params: Dict[str, Any]) -> tuple:
    """执行单个工具，返回 (是否成功, 结果字典或错误信息字符串)。

    把「工具不存在 / 依赖缺失 / 执行异常」都转化为可读字符串，
    作为「观察」反馈给大模型，让其有机会恢复。
    """
    skills_meta = harness.list_skills()
    if tool not in skills_meta:
        return False, f"工具 '{tool}' 不存在，可用: {list(skills_meta.keys())}"

    ok, missing = harness.check_dependencies(tool)
    if not ok:
        return False, f"工具 '{tool}' 缺少依赖 {missing}，无法执行"

    try:
        result = harness.execute(tool, **params)
        return True, result
    except Exception as e:
        return False, f"工具执行失败: {e}"


def answer(
    question: str,
    skills_meta: Dict[str, Dict[str, Any]],
    harness,
    max_iterations: int = 8,
    on_step: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """ReAct 主循环。

    参数：
        question        用户的问题
        skills_meta     harness.list_skills() 的结果
        harness         FileSkillHarness 实例（用于执行工具）
        max_iterations  最大推理轮数（默认 8，防止死循环）
        on_step         可选回调，每产生一个步骤（思考/调用/观察/最终）时回调，
                        便于 CLI 实时打印推理过程

    返回：
        {"answer": str, "steps": [...], "iterations": int}
    """
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": _build_qa_system_prompt(skills_meta)},
        {"role": "user", "content": question},
    ]
    steps: List[Dict[str, Any]] = []

    for i in range(max_iterations):
        # 请求大模型，得到本轮动作
        raw = call_chat_api(messages)
        parsed = _extract_json(raw)

        thought = parsed.get("thought", "")
        action = parsed.get("action")

        # 终止：最终回答
        if action == "final_answer":
            ans = parsed.get("answer", "")
            step = {
                "iteration": i + 1,
                "type": "final_answer",
                "thought": thought,
                "answer": ans,
            }
            steps.append(step)
            if on_step:
                on_step(step)
            return {"answer": ans, "steps": steps, "iterations": i + 1}

        # 调用工具
        if action == "call_tool":
            tool = parsed.get("tool")
            params = parsed.get("params", {})
            step = {
                "iteration": i + 1,
                "type": "call_tool",
                "thought": thought,
                "tool": tool,
                "params": params,
            }
            steps.append(step)
            if on_step:
                on_step(step)

            # 执行工具，得到观察
            success, obs = _execute_tool(harness, tool, params)
            observation = obs if isinstance(obs, str) else json.dumps(
                obs, ensure_ascii=False
            )
            obs_step = {
                "iteration": i + 1,
                "type": "observation",
                "success": success,
                "observation": observation,
            }
            steps.append(obs_step)
            if on_step:
                on_step(obs_step)

            # 把模型输出 + 观察结果追加到历史，进入下一轮
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {"role": "user", "content": f"观察结果: {observation}"}
            )
            continue

        # 无法识别的 action：把纠正信息反馈给模型，让其重试
        correction = (
            f"无法识别的 action: {action}，请输出 call_tool 或 final_answer。"
        )
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": correction})

    # 达到最大轮数仍未给出最终答案
    fallback = (
        f"已达到最大推理轮数({max_iterations})，未能给出最终答案。"
        f"最近步骤: {steps[-1] if steps else '无'}"
    )
    return {"answer": fallback, "steps": steps, "iterations": max_iterations}
