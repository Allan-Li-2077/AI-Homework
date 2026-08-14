"""
Sub-Agent 可用工具集

每个工具 = (callable, json_schema)。纯 Python 实现，无第三方依赖，
harness 开箱即跑（mock 模式下 sub-agent 也能用这些工具真干活）。

设计原则：
  - 工具是无状态的纯函数，任意 sub-agent 都可按需组合
  - 文件类工具默认只在 workspace/ 下操作，避免越权读写源码
  - calculator 用 AST 白名单做安全沙箱，不调用 eval/exec
"""

import ast
import re
import operator as op
from pathlib import Path

WORKSPACE = Path(__file__).parent / "workspace"


def _resolve(path: str) -> Path:
    """把任意路径安全地归一到 workspace/ 下，防止 sub-agent 越权访问。"""
    p = Path(path)
    if not p.is_absolute():
        p = WORKSPACE / p
    try:
        p = p.resolve()
    except Exception:
        pass
    return p


# ── 安全算术计算 ────────────────────────────────────────────────────────────

_BINOPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
    ast.Pow: op.pow, ast.Mod: op.mod, ast.FloorDiv: op.floordiv,
}
_UNARYOPS = {ast.UAdd: op.pos, ast.USub: op.neg}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("不支持的表达式（仅允许数字与 + - * / // % ** 和括号）")


def calculator(expression: str) -> str:
    """安全算术计算，基于 AST 白名单，不使用 eval/exec。"""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree.body)
        return f"{expression} = {result}"
    except Exception as e:
        return f"计算错误: {e}"


# ── 文件类工具（只读） ───────────────────────────────────────────────────────

def read_file(path: str) -> str:
    p = _resolve(path)
    if not p.is_file():
        return f"错误：文件不存在 {path}"
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = p.read_bytes()[:200]
        return raw.decode("utf-8", errors="replace") + " ...(二进制)"
    if len(text) > 4000:
        text = text[:4000] + f"\n...(截断，共 {len(text)} 字符)"
    return text


def list_files(directory: str = ".") -> str:
    d = _resolve(directory)
    if not d.is_dir():
        return f"错误：目录不存在 {directory}"
    entries = []
    for child in sorted(d.iterdir()):
        tag = "/" if child.is_dir() else ""
        size = child.stat().st_size if child.is_file() else ""
        entries.append(f"{child.name}{tag}" + (f"  ({size}B)" if size else ""))
    return f"{directory}（{len(entries)} 项）:\n" + "\n".join(entries)


def search(pattern: str, path: str = ".") -> str:
    """递归搜索文件内容（正则匹配），返回 文件:行号: 内容。"""
    root = _resolve(path)
    if not root.exists():
        return f"错误：路径不存在 {path}"
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"错误：非法正则 {e}"

    matches = []
    files = root.rglob("*") if root.is_dir() else [root]
    for file in files:
        if not file.is_file() or file.suffix in (".html", ".png", ".jpg", ".zip"):
            continue
        try:
            lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if regex.search(line):
                matches.append(f"{file.relative_to(WORKSPACE) if WORKSPACE in file.parents or file == WORKSPACE else file}:{i}: {line.strip()[:120]}")
                if len(matches) >= 30:
                    matches.append("...(结果过多，已截断)")
                    return f"匹配 {len(matches)} 处:\n" + "\n".join(matches)
    if not matches:
        return f"未找到匹配 '{pattern}' 的内容"
    return f"匹配 {len(matches)} 处:\n" + "\n".join(matches)


# ── 工具注册表 ───────────────────────────────────────────────────────────────

TOOLS = {
    "read_file":  read_file,
    "list_files": list_files,
    "search":     search,
    "calculator": calculator,
}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "read_file", "description": "读取 workspace 下某个文件的内容",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string", "description": "文件路径"}},
                       "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "list_files", "description": "列出 workspace 下某目录的文件和子目录",
        "parameters": {"type": "object",
                       "properties": {"directory": {"type": "string", "default": "."}},
                       "required": []}}},
    {"type": "function", "function": {
        "name": "search", "description": "递归搜索文件内容（正则）",
        "parameters": {"type": "object",
                       "properties": {"pattern": {"type": "string", "description": "正则表达式"},
                                       "path": {"type": "string", "default": "."}},
                       "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "calculator", "description": "安全算术计算（+ - * / // % ** 和括号）",
        "parameters": {"type": "object",
                       "properties": {"expression": {"type": "string"}},
                       "required": ["expression"]}}},
]


def schemas_for(names: list[str]) -> list[dict]:
    """按工具名列表过滤出对应的 function calling schema。"""
    return [s for s in TOOL_SCHEMAS if s["function"]["name"] in names]


def call_tool(name: str, args: dict) -> str:
    """统一工具调用入口，出错返回错误字符串而非抛异常。"""
    fn = TOOLS.get(name)
    if fn is None:
        return f"错误：未知工具 '{name}'"
    try:
        return str(fn(**args))
    except TypeError as e:
        return f"错误：工具参数错误 {name}({args}): {e}"
    except Exception as e:
        return f"错误：工具执行失败 {name}: {e}"
