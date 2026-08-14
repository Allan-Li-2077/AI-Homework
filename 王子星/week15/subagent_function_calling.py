"""
Function Calling 版 ReAct Agent —— 支持 Subagent 并行派发

在 react_function_calling_multiturn.py 的基础上新增「主 Agent 可派发 Subagent」的能力：
  1. 主 Agent 仍是普通的 Function Calling 循环，但多了一个 dispatch_subagents 工具。
     模型自己判断问题要不要拆成多个侧面并行调研，还是直接调 web_search/calculator
     自己一步步答——这是 LLM 自主路由，不是写死的分支逻辑。
  2. dispatch_subagents 一次接收多个子课题（JSON 字符串数组），每个子课题起一个
     独立的、只有 web_search+calculator 两个工具的迷你 Function Calling 循环
     （run_subagent），用 ThreadPoolExecutor 并行跑，wall-clock ≈ max(单个耗时)。

"""

import os
import json
import math
import time
import logging
import argparse
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Generator

from openai import OpenAI

from tavily_search import tavily_search, format_search_result

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ── 模型选择 ──

PROVIDER = os.getenv("AGENT_PROVIDER", "deepseek").lower()  # "deepseek" 或 "qwen"

if PROVIDER == "qwen":
    client = OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    MODEL = os.getenv("AGENT_MODEL", "qwen3.7-plus")
else:
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )
    MODEL = os.getenv("AGENT_MODEL", "deepseek-v4-flash")


# ── System Prompt ───

MAIN_SYSTEM_PROMPT = """你是一个通用智能助手，既能回答金融相关问题，也能回答任何联网可查的通用问题。

你有 3 个工具：
- web_search：联网搜索一次，适合"单一事实、一次搜索就能答"的问题（如某个数字、某条新闻）
- calculator：数学计算，涉及数字运算（增长率、差值、比例等）必须用它，不能心算
- dispatch_subagents：派发多个子调研员并行调研，每个子调研员独立联网搜索+计算，
  适合"一个问题包含多个独立侧面，需要分别查证再汇总"的情况

【关键决策原则】
- 如果问题只需一次搜索就能拿到答案（比如"今天黄金价格是多少"），直接用 web_search，不要小题大做派发 subagent
- 如果问题明显包含 2 个及以上相对独立的侧面（比如"调研某公司：股价+财报+竞对"，
  或"比较 A 和 B 在多个维度上的差异"，或"某事件的背景+影响+各方反应"），
  必须用 dispatch_subagents 把每个侧面拆成一个子课题交给子调研员并行处理，
  不要自己在主线程里对每个侧面串行调用 web_search
- 拿到 dispatch_subagents 的汇总结果后，把各子课题结果整合成结构化的最终回答，
  分维度组织、指出信息来源，末尾如有不确定性要说明
- 如果所有工具都无法获取足够信息，直接说明原因，不要编造

回答金融问题时，用 web_search 查最新数据而不是依赖自己可能过时的知识；
回答通用问题（新闻、体育、科技动态等）同理。"""

SUBAGENT_SYSTEM_PROMPT = """你是一个子调研员，只负责完成分配给你的这一个子课题。
你有 2 个工具：web_search（联网搜索）、calculator（数学计算，涉及数字必须用它）。
围绕子课题联网搜索、必要时计算，最后给出简洁但有数据支撑的结论，并标注信息来源。"""


# ── 工具实现 ──────────────────────────────────────────────────────────────────

_SAFE_NAMES = {k: v for k, v in math.__dict__.items() if not k.startswith("_")}
_SAFE_NAMES.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})


def tool_calculator(expr: str) -> str:
    """安全计算数学表达式，支持四则运算和 math 模块函数。"""
    try:
        result = eval(expr, {"__builtins__": {}}, _SAFE_NAMES)  # noqa: S307
        return str(round(float(result), 6))
    except Exception as e:
        return f"计算出错: {e}，表达式: {expr}"


def tool_web_search(query: str, max_results: int = 5) -> str:
    """联网搜索一次，返回格式化后的摘要+结果列表。"""
    return format_search_result(tavily_search(query, max_results=max_results))


# dispatch_subagents 的实现依赖 run_subagent，定义在下面，注册表在文件末尾统一收拢


# ── Subagent：独立的迷你 Function Calling 循环（只有 web_search + calculator） ──

SUBAGENT_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索一次，获取某个具体子课题相关的最新信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，尽量具体"},
                    "max_results": {"type": "integer", "description": "返回结果数量，默认5", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "安全计算数学表达式，涉及数字运算时必须用它，不能心算",
            "parameters": {
                "type": "object",
                "properties": {
                    "expr": {"type": "string", "description": "数学表达式，如 '(747 - 524) / 524 * 100'"},
                },
                "required": ["expr"],
            },
        },
    },
]

SUBAGENT_TOOLS_MAP = {
    "web_search": tool_web_search,
    "calculator": tool_calculator,
}


def run_subagent(topic: str, max_steps: int = 6) -> dict:
    """独立跑一个子调研员的 Function Calling 循环，返回 {final_answer, trace, duration}。
    trace 记录该子调研员每一步的工具调用，供主流程打印时展示子过程。
    """
    t0 = time.time()
    messages = [
        {"role": "system", "content": SUBAGENT_SYSTEM_PROMPT},
        {"role": "user", "content": topic},
    ]
    trace = []
    final_answer = ""

    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model=MODEL, messages=messages,
            tools=SUBAGENT_TOOLS_SCHEMA, tool_choice="auto", temperature=0,
        )
        msg = response.choices[0].message

        if response.choices[0].finish_reason == "stop" or not msg.tool_calls:
            final_answer = msg.content or "（子调研员返回空内容）"
            messages.append({"role": "assistant", "content": final_answer})
            break

        messages.append(msg)
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                args = {}
            fn = SUBAGENT_TOOLS_MAP.get(name)
            observation = fn(**args) if fn else f"未知工具 '{name}'"
            trace.append({"action": name, "action_input": args, "observation": str(observation)})
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(observation)})
    else:
        # 循环全部耗尽都没 break（即模型一直在调工具，没给 Final Answer）
        # 不直接认输：拿已收集到的 observation 强制收尾一次，禁止再调工具
        try:
            forced = client.chat.completions.create(
                model=MODEL,
                messages=messages + [{"role": "user", "content":
                    "请基于以上已经获取到的搜索/计算结果，直接给出你对该子课题的结论（不要再调用任何工具，如信息不足就说明还缺什么）。"}],
                tool_choice="none", temperature=0,
            )
            final_answer = forced.choices[0].message.content or "（强制收尾仍未获得有效内容）"
        except Exception as e:
            final_answer = f"（子调研员已达最大步数 {max_steps}，强制收尾也失败: {type(e).__name__}）"

    duration = round(time.time() - t0, 2)
    return {"final_answer": final_answer, "trace": trace, "duration": duration}


def tool_dispatch_subagents(subtopics: list, on_subagent_done=None) -> str:
    """并行派发多个子调研员，收齐结果汇总成文本喂回主 Agent。
    subtopics: 子课题字符串列表（Function Calling 原生数组参数，不用像纯文本 ReAct
    那样拿 "|" 分隔字符串再手动 split）。
    并行用 ThreadPoolExecutor：wall-clock ≈ max(单个耗时)，而不是 sum。"""
    subtopics = [s.strip() for s in subtopics if isinstance(s, str) and s.strip()][:6]
    if not subtopics:
        return "未收到有效子课题"

    defs = [(f"sub_{uuid.uuid4().hex[:6]}", topic) for topic in subtopics]

    t0 = time.time()
    results = {}
    with ThreadPoolExecutor(max_workers=len(defs)) as pool:
        futs = {pool.submit(run_subagent, topic): (sid, topic) for sid, topic in defs}
        for fut in as_completed(futs):
            sid, topic = futs[fut]
            res = fut.result()
            results[sid] = (topic, res)
            if on_subagent_done:
                on_subagent_done(sid, topic, res)

    wall = round(time.time() - t0, 2)
    serial_sum = round(sum(r["duration"] for _, r in results.values()), 2)
    speedup = round(serial_sum / wall, 2) if wall else 0

    parts = [f"【子课题: {topic}】(用时{r['duration']}s，{len(r['trace'])}次工具调用)\n{r['final_answer'][:600]}"
             for topic, r in results.values()]
    header = (f"并行调研完成：{len(defs)} 个子调研员，wall-clock {wall}s "
              f"(若串行需 {serial_sum}s，加速 {speedup}×)")
    return header + "\n\n" + "\n\n".join(parts)


# ── 主 Agent 工具注册表 & Schema ──────────────────────────────────────────────

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索一次，适合单一事实、一次搜索就能答的问题",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，尽量具体"},
                    "max_results": {"type": "integer", "description": "返回结果数量，默认5", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "安全计算数学表达式，涉及数字运算（增长率/差值/比例等）必须用它",
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
            "name": "dispatch_subagents",
            "description": (
                "派发多个子调研员并行调研，每个子课题一个独立的子调研员（各自联网搜索+计算）。"
                "适合问题包含 2 个及以上独立侧面、需要分别查证再汇总的情况。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subtopics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "子课题列表，每个元素是一个独立的调研子课题，2~6 个",
                    },
                },
                "required": ["subtopics"],
            },
        },
    },
]


# ── 主循环：Function Calling 版 ReAct，多轮 + Subagent 派发 ─────────────────

def new_session() -> list:
    return [{"role": "system", "content": MAIN_SYSTEM_PROMPT}]


def run(question: str, max_steps: int = 10, history: list | None = None) -> Generator[dict, None, None]:
    """
    执行主 Agent 的 Function Calling 循环，yield 每一步结构化结果。

    """
    messages = history if history is not None else new_session()
    messages.append({"role": "user", "content": question})
    used_subagent = False

    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model=MODEL, messages=messages,
            tools=TOOLS_SCHEMA, tool_choice="auto", temperature=0,
        )
        msg = response.choices[0].message
        reason = response.choices[0].finish_reason

        if reason == "stop" or not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content or ""})
            yield {
                "step": step, "type": "final", "thought": "",
                "answer": msg.content or "（模型返回空内容）",
                "method": "subagent" if used_subagent else "direct",
            }
            return

        messages.append(msg)

        for tool_call in msg.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            if tool_name == "dispatch_subagents":
                used_subagent = True
                subagent_events = []
                observation = tool_dispatch_subagents(
                    tool_args.get("subtopics", []),
                    on_subagent_done=lambda sid, topic, res: subagent_events.append(
                        {"id": sid, "topic": topic, "duration": res["duration"],
                         "trace": res["trace"], "final_answer": res["final_answer"]}),
                )
                yield {
                    "step": step, "type": "subagent_dispatch",
                    "action_input": tool_args, "observation": observation,
                    "subagents": subagent_events,
                }
            elif tool_name == "web_search":
                observation = tool_web_search(**tool_args)
                yield {"step": step, "type": "action", "action": tool_name,
                       "action_input": tool_args, "observation": str(observation)}
            elif tool_name == "calculator":
                observation = tool_calculator(**tool_args)
                yield {"step": step, "type": "action", "action": tool_name,
                       "action_input": tool_args, "observation": str(observation)}
            else:
                observation = f"未知工具 '{tool_name}'"
                yield {"step": step, "type": "action", "action": tool_name,
                       "action_input": tool_args, "observation": observation}

            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(observation)})

    yield {"step": max_steps + 1, "type": "max_steps",
           "answer": f"已达最大步数 {max_steps}，未能得出最终答案",
           "method": "subagent" if used_subagent else "direct"}


# ── CLI 打印 ──────────────────────────────────────────────────────────────────

COLORS = {
    "action": "\033[33m", "obs": "\033[32m", "final": "\033[35m",
    "error": "\033[31m", "dispatch": "\033[34m", "sub": "\033[36m", "reset": "\033[0m",
}

def _c(color: str, text: str) -> str:
    return f"{COLORS[color]}{text}{COLORS['reset']}"


def _print_one_round(question: str, max_steps: int, history: list):
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    print(f"模型: {PROVIDER}/{MODEL}  实现: Function Calling + Subagent 并行派发")
    print('='*60)

    start = time.time()

    for step_data in run(question, max_steps=max_steps, history=history):
        stype = step_data["type"]

        if stype == "action":
            print(f"\n[Step {step_data['step']}]")
            print(_c("action", f"🔧 Action:  {step_data['action']}"))
            print(_c("action", f"   Input:   {json.dumps(step_data['action_input'], ensure_ascii=False)}"))
            print(_c("obs", f"👁  Obs:     {step_data['observation'][:300]}"))

        elif stype == "subagent_dispatch":
            print(f"\n[Step {step_data['step']}]")
            print(_c("dispatch", f"🧩 Action:  dispatch_subagents（触发并行 Subagent）"))
            print(_c("dispatch", f"   Input:   {json.dumps(step_data['action_input'], ensure_ascii=False)}"))
            for sub in step_data["subagents"]:
                print(_c("sub", f"   └─ Subagent[{sub['id']}] 子课题: {sub['topic']} (用时{sub['duration']}s)"))
                for t in sub["trace"]:
                    print(_c("sub", f"        · {t['action']}({json.dumps(t['action_input'], ensure_ascii=False)[:60]}) "
                                    f"→ {t['observation'][:120]}"))
                print(_c("sub", f"        结论: {sub['final_answer'][:200]}"))
            print(_c("obs", f"👁  汇总 Obs: {step_data['observation'][:200]}"))

        elif stype == "final":
            elapsed = time.time() - start
            method_label = "主 Agent 派发 Subagent 并行调研" if step_data["method"] == "subagent" \
                else "主 Agent 直接回答（可能用了 web_search/calculator，也可能完全不用工具）"
            print(f"\n{'─'*60}")
            print(_c("final", f"\n✅ Final Answer:\n{step_data['answer']}"))
            print(f"\n📌 本次回答方式: {method_label}")
            print(f"共 {step_data['step']} 步，耗时 {elapsed:.1f}s")

        elif stype in ("error", "max_steps"):
            print(_c("error", f"\n⚠️  {step_data.get('answer', '')}"))


EXAMPLE_QUESTIONS = [
    "帮我调研一下英伟达：最新股价走势、主要竞争对手、以及最近一个季度的营收情况",
    "特斯拉最近的财报表现、机器人业务进展、和主要竞争对手的对比",
    "2024年全球锂电池行业现状：市场规模、主要厂商竞争格局、技术趋势",
    "美联储最新的利率决议，对美股、黄金、原油分别会有什么影响",
    "比较一下比特币和以太坊最近的价格走势、市场情绪、和主要利好利空消息"
]


def run_interactive_and_print(max_steps: int = 10):
    print(f"\n{'='*60}")
    print(f"Function Calling ReAct Agent（支持 Subagent 并行派发）")
    print(f"模型提供方: {PROVIDER}  模型: {MODEL}")
    print("提示：直接回车（不输入内容）或按 Ctrl+C 结束本次会话")
    print("可以试试这些容易触发 Subagent 并行调研的问题：")
    for i, q in enumerate(EXAMPLE_QUESTIONS, 1):
        print(f"  {i}. {q}")
    print('='*60)

    history = new_session()

    try:
        while True:
            try:
                question = input("\n请输入问题 > ").strip()
            except EOFError:
                break

            if not question:
                print("\n（收到空输入，结束会话）")
                break

            _print_one_round(question, max_steps, history)
    except KeyboardInterrupt:
        print("\n\n（收到 Ctrl+C，结束会话）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument("--provider", choices=["deepseek", "qwen"], default=None,
                        help="覆盖 AGENT_PROVIDER 环境变量，选择用 deepseek 还是 qwen")
    args = parser.parse_args()

    if args.provider and args.provider != PROVIDER:
        # 命令行显式指定时，重新初始化 client/MODEL（不常用，主要走环境变量）
        PROVIDER = args.provider
        if PROVIDER == "qwen":
            client = OpenAI(api_key=os.getenv("DASHSCOPE_API_KEY"),
                            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
            MODEL = os.getenv("AGENT_MODEL", "qwen3.7-plus")
        else:
            client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"),
                            base_url="https://api.deepseek.com")
            MODEL = os.getenv("AGENT_MODEL", "deepseek-v4-flash")

    run_interactive_and_print(args.max_steps)
