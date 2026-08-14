"""
文件系统工具 — 代码审查 subagent 的"眼睛"

提供审查代码所需的三个核心能力：
  1. read_file   — 读取代码文件（支持行范围，避免一次灌太多）
  2. search_code — 搜索代码模式（grep 语义，支持文件类型过滤）
  3. list_files  — 列出目录结构

所有工具接受字符串参数（ReAct 兼容），返回格式化的文本结果。
工具通过 PROJECT_ROOT 环境变量指定要审查的项目根目录，默认为当前目录。

设计原则：
  - 每个工具参数都是一个字符串（JSON 格式），方便 ReAct Action Input
  - 返回结果截断到合理长度，避免撑爆 LLM context
  - 安全：限制访问范围在 PROJECT_ROOT 内
"""

import os
import re
import json
import fnmatch
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 项目根目录：审查哪个项目 ──────────────────────────────────────────────
def _get_project_root() -> Path:
    root = os.getenv("PROJECT_ROOT", os.getcwd())
    return Path(root).resolve()


def _safe_path(path_str: str) -> Path:
    """安全解析路径，限制在 PROJECT_ROOT 内。"""
    root = _get_project_root()
    p = (root / path_str).resolve()
    if not str(p).startswith(str(root)):
        raise ValueError(f"路径越界: {path_str}")
    return p


# ── 工具函数 ──────────────────────────────────────────────────────────────

def read_file(params_str: str, **_kw) -> str:
    """
    读取文件内容，支持行范围。
    参数格式（JSON 字符串）：
      {"path": "src/main.py"}                              — 读整个文件
      {"path": "src/main.py", "start": 1, "end": 50}      — 读第 1-50 行
      {"path": "src/main.py", "start": 100}                — 从第 100 行开始读
    返回文件内容（前 2000 字符截断）。
    """
    try:
        params = json.loads(params_str)
    except json.JSONDecodeError:
        # 兼容纯路径字符串
        params = {"path": params_str}

    path = params.get("path", "")
    if not path:
        return "错误: 缺少 path 参数"

    try:
        fp = _safe_path(path)
    except ValueError as e:
        return str(e)

    if not fp.exists():
        return f"文件不存在: {path}"

    if fp.is_dir():
        return f"'{path}' 是目录，请用 list_files 查看其内容"

    try:
        lines = fp.read_text(encoding="utf-8", errors="replace").split("\n")
    except Exception as e:
        return f"读取失败: {e}"

    start = max(0, int(params.get("start", 1)) - 1)
    end = min(len(lines), int(params.get("end", len(lines))))
    if "start" in params and "end" not in params:
        end = len(lines)

    selected = lines[start:end]
    # 加行号
    numbered = [f"{start + i + 1:4d}| {selected[i]}" for i in range(len(selected))]
    result = "\n".join(numbered)
    # 截断
    if len(result) > 2000:
        result = result[:2000] + f"\n... (截断，共 {len(lines)} 行)"
    # 加文件信息头
    header = f"📄 {path} (行 {start + 1}-{end}, 共 {len(lines)} 行)\n{'=' * 50}\n"
    return header + result


def search_code(params_str: str, **_kw) -> str:
    """
    在项目中搜索代码模式（grep）。
    参数格式（JSON 字符串）：
      {"pattern": "def main"}                              — 搜索文本
      {"pattern": "TODO", "glob": "*.py"}                  — 按文件类型过滤
      {"pattern": "eval\\(", "glob": "*.py", "dir": "src"} — 指定子目录
    返回匹配行列表（最多 30 条，含文件名和行号）。
    """
    try:
        params = json.loads(params_str)
    except json.JSONDecodeError:
        params = {"pattern": params_str}

    pattern = params.get("pattern", "")
    if not pattern:
        return "错误: 缺少 pattern 参数"

    file_glob = params.get("glob", "*")
    subdir = params.get("dir", "")

    root = _get_project_root()
    search_root = root
    if subdir:
        try:
            search_root = _safe_path(subdir)
        except ValueError as e:
            return str(e)
        if not search_root.exists():
            return f"目录不存在: {subdir}"

    # 编译正则（不区分大小写的简单匹配或正则）
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        # 不是正则，用简单包含匹配
        regex = None

    results = []
    checked = 0
    max_results = 30

    # 跳过这些目录
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv",
                 ".idea", ".vscode", "dist", "build", ".next", "outputs"}

    for dirpath, dirnames, filenames in os.walk(search_root):
        # 过滤目录
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]

        for fname in filenames:
            if not fnmatch.fnmatch(fname, file_glob):
                continue
            fpath = os.path.join(dirpath, fname)
            rel = os.path.relpath(fpath, root)
            checked += 1

            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for lno, line in enumerate(f, 1):
                        matched = False
                        if regex:
                            matched = bool(regex.search(line))
                        else:
                            matched = pattern.lower() in line.lower()
                        if matched:
                            results.append({
                                "file": rel, "line": lno,
                                "text": line.strip()[:120]
                            })
                            if len(results) >= max_results:
                                break
            except Exception:
                continue

            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    if not results:
        return f"未找到匹配 '{pattern}' 的结果（检查了 {checked} 个文件）"

    lines = [f"🔍 搜索 '{pattern}' 结果（{len(results)} 条匹配）\n{'=' * 50}"]
    for r in results[:max_results]:
        lines.append(f"  {r['file']}:{r['line']}  {r['text']}")

    if len(results) >= max_results:
        lines.append(f"  ... (已达 {max_results} 条上限)")

    return "\n".join(lines)


def list_files(params_str: str = "", **_kw) -> str:
    """
    列出目录结构。
    参数格式（JSON 字符串）：
      ""                               — 列出项目根目录
      {"dir": "src"}                   — 列出指定子目录
      {"dir": "src", "depth": 2}       — 指定深度（默认 2）
    返回目录树文本。
    """
    params = {}
    if params_str:
        try:
            params = json.loads(params_str)
        except json.JSONDecodeError:
            params = {"dir": params_str}

    subdir = params.get("dir", "")
    depth = int(params.get("depth", 2))

    root = _get_project_root()
    target = root
    if subdir:
        try:
            target = _safe_path(subdir)
        except ValueError as e:
            return str(e)

    if not target.exists():
        return f"目录不存在: {subdir}"

    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv",
                 ".idea", ".vscode", "dist", "build", ".next", "outputs"}

    lines = [f"📁 {'/' + subdir if subdir else '项目根目录'}\n{'=' * 50}"]

    def _walk(d: Path, prefix: str = "", current_depth: int = 0):
        if current_depth > depth:
            return
        entries = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        # 过滤隐藏文件和跳过目录
        entries = [e for e in entries
                   if not e.name.startswith(".") and e.name not in skip_dirs]
        for i, entry in enumerate(entries):
            is_last = (i == len(entries) - 1)
            connector = "└── " if is_last else "├── "
            rel = entry.relative_to(root)
            lines.append(f"{prefix}{connector}{entry.name}" +
                         ("/" if entry.is_dir() else ""))
            if entry.is_dir() and current_depth < depth:
                extension = "    " if is_last else "│   "
                _walk(entry, prefix + extension, current_depth + 1)

    _walk(target)
    if len(lines) > 80:
        lines = lines[:80]
        lines.append("... (截断)")

    return "\n".join(lines)


# ── 工具注册表（统一供 agents.py 使用）───────────────────────────────────

def get_file_tools() -> dict:
    """返回文件系统工具注册表。格式: {name: (function, description)}"""
    return {
        "read_file": (
            read_file,
            "读取文件。参数 JSON: {\"path\": \"src/main.py\"[, \"start\": 行号, \"end\": 行号]}"
        ),
        "search_code": (
            search_code,
            "搜索代码模式。参数 JSON: {\"pattern\": \"def main\"[, \"glob\": \"*.py\", \"dir\": \"src\"]}"
        ),
        "list_files": (
            list_files,
            "列出目录。参数 JSON: {\"dir\": \"src\"[, \"depth\": 2]} 或不传参列出根目录"
        ),
    }


# ── 自测 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging as _l
    _l.basicConfig(level=_l.INFO)

    # 测试在当前项目目录
    print("=== list_files ===")
    print(list_files(""))
    print("\n=== search_code ===")
    print(search_code('{"pattern": "def ", "glob": "*.py"}'))
    print("\n=== read_file ===")
    print(read_file('{"path": "src/file_tools.py", "start": 1, "end": 20}'))
