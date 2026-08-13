"""
异构 Worker 注册表 + 安全计算器工具

教学重点：
  1. 「agent 的能力由工具集定义」：三个 worker 是同一套执行机制，
     区别只在 system_prompt + tools——研究员只会上网、分析师只会按计算器、
     写手没有工具（纯创作，不走 ReAct）
  2. 模型分层（教程 P21）：调研/计算是事实性任务 temperature 0.0，
     写手是创作性任务 temperature 0.7；路由层零 LLM 成本（纯 Python 规则）
  3. calculator 用 ast 白名单实现，拒绝一切函数调用/属性访问——
     工具实现要防注入（week12 直接用 eval 有安全隐患）
  4. 无 TAVILY_API_KEY 时 researcher 自动降级为「基于知识作答」模式，
     系统不依赖外部服务也能完整演示
"""
import ast
import logging
import operator
import os

from tavily_search import tavily_search, format_search_result

logger = logging.getLogger(__name__)

# 是否有联网搜索能力（无 key 时降级，见 effective_config）
SEARCH_AVAILABLE = bool(os.getenv("TAVILY_API_KEY"))


# ── 安全计算器：ast 白名单，不用 eval ─────────────────────────────────
_ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def safe_calc(expr: str) -> str:
    """计算数学表达式（仅数字和 + - * / ** % 括号）。
    例: safe_calc("100*(1.3**2)") -> "169"
    拒绝：函数调用、属性访问、__import__ 等一切白名单外成分。"""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return f"表达式语法错误: {e}"
    try:
        value = _eval_node(tree.body)
    except (ValueError, ZeroDivisionError) as e:
        return f"计算失败: {e}"
    if isinstance(value, float):
        value = int(value) if value.is_integer() else round(value, 4)
    return str(value)


def _eval_node(node):
    """递归求值，白名单外节点一律抛 ValueError。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"不支持的表达式成分 {type(node).__name__}（只允许数字和 + - * / ** %）")


# ── worker 工具（签名兼容 ReActLoop 的 fn(action_input) 调用）────────
def _search_tool(query: str, **_):
    return format_search_result(tavily_search(query))


def _calc_tool(expr: str, **_):
    return safe_calc(expr)


# ── 三个异构 worker 的 system prompt ─────────────────────────────────
RESEARCHER_SYSTEM = """你是资深行业研究员。你的任务是完成用户指定的调研课题。

要求：
1. 尽量使用 web_search 工具联网查资料（搜索失败时基于你的知识作答）
2. 输出要点式调研结论，每个要点尽量带数据支撑
3. 只做调研，不写整篇成品文案、不做数值计算
4. 结尾附一个 JSON 块（```json 包裹或直接 { ... }）：
   {"key_findings": ["要点1", "要点2", ...]}"""

RESEARCHER_SYSTEM_KNOWLEDGE = """你是资深行业研究员。你的任务是完成用户指定的调研课题。

注意：当前没有联网工具，请基于你自己的知识作答，数字给出量级并标注「估算」。

要求：
1. 输出要点式调研结论，每个要点尽量带数据支撑（估算）
2. 只做调研，不写整篇成品文案、不做数值计算
3. 结尾附一个 JSON 块（```json 包裹或直接 { ... }）：
   {"key_findings": ["要点1", "要点2", ...]}"""

ANALYST_SYSTEM = """你是数据分析师。你的任务是完成用户指定的计算分析。

铁律：所有数学计算必须调用 calculator 工具完成，禁止心算！

步骤：
1. 用 calculator 分步算：CAGR = (末期/基期)**(1/年数)-1（中间量算完再算最终值，不要合并）
2. 如需同比增速，每个年份各算一次
3. 算完立即 Final Answer，不要反复重算
4. 结尾附 JSON 块：
   {"calc_steps": ["6188/3817=1.6212", ...], "conclusion": "..."}"""

WRITER_SYSTEM = """你是资深文案写手。你会收到一份调研/数据材料摘要和写作任务。

要求：
1. 只使用材料中的事实与数据，不编造
2. 面向写作任务指定的读者，文风生动可读
3. 直接输出成品：第一行是标题，后面是正文。不要输出 JSON、不要解释写作过程"""


# ── WORKERS 注册表：异构体现在 prompt + tools + mode + temperature ───
WORKERS = {
    "researcher": {
        "label": "行业研究员",
        "color": "#4f8cff",
        "shape": "circle",
        "mode": "react",          # 有工具 → ReAct 循环（Reason + Act）
        "temperature": 0.0,       # 事实性任务，低温度
        "max_steps": 4,
        "system_prompt": RESEARCHER_SYSTEM,
        "tools": {"web_search": (_search_tool, "联网搜索一次，参数=查询词")},
    },
    "data_analyst": {
        "label": "数据分析师",
        "color": "#ffb020",
        "shape": "circle",
        "mode": "react",
        "temperature": 0.0,
        "max_steps": 6,          # 分步计算需要多轮工具调用（CAGR 3~4 步 + 同比 2 步）
        "system_prompt": ANALYST_SYSTEM,
        "tools": {"calculator": (_calc_tool, "计算数学表达式，仅支持数字和 + - * / ** % 括号")},
    },
    "writer": {
        "label": "文案写手",
        "color": "#2ee6a0",
        "shape": "rect",
        "mode": "single_shot",    # 无工具 → 单次调用（ReAct 没有 Act 环节）
        "temperature": 0.7,       # 创作性任务，高温度
        "max_steps": 1,
        "system_prompt": WRITER_SYSTEM,
        "tools": {},
    },
}


def effective_config(name: str) -> dict:
    """返回 worker 配置副本。无 Tavily key 时 researcher 降级：
    mode → single_shot（无工具就不跑 ReAct），prompt 换成「基于知识作答」版。"""
    cfg = dict(WORKERS[name])
    if name == "researcher" and not SEARCH_AVAILABLE:
        cfg["mode"] = "single_shot"
        cfg["system_prompt"] = RESEARCHER_SYSTEM_KNOWLEDGE
        logger.info("未设置 TAVILY_API_KEY，研究员降级为「基于知识作答」模式")
    return cfg


if __name__ == "__main__":
    # 自测：calculator 白名单 + 注入拒绝 + 降级开关
    assert float(safe_calc("100*(1.3**2)")) == 169.0, safe_calc("100*(1.3**2)")
    assert safe_calc("(6188/3817)**0.5") == "1.2733", safe_calc("(6188/3817)**0.5")
    for evil in ["__import__('os').system('dir')", "open('x')", "(1).__class__",
                 "pow(2,3)", "[1,2,3][0]", "exit()"]:
        assert safe_calc(evil).startswith(("计算失败", "表达式语法错误")), (evil, safe_calc(evil))
    print("calculator 白名单自测通过（正常计算 OK / 注入拒绝 OK）")
    print("Tavily 可用:", SEARCH_AVAILABLE, "| researcher 模式:",
          effective_config("researcher")["mode"])
    print("WORKERS:", {k: v["mode"] for k, v in WORKERS.items()})
