"""
任务规划与执行引擎 — 从 SKILL.md 驱动的通用执行框架

核心架构：
  1. TaskNode：任务节点，含 id / title / command / depends_on / status / layer
  2. TaskGraph：任务图，管理节点与依赖关系，提供拓扑分层
  3. TaskExecutor：并行执行引擎，按拓扑层执行，同层并行、层间顺序（兼容旧 JSON 模式）
  4. LivePlanDisplay：原地刷新任务面板，显示依赖关系与层级
  5. ScriptExecutor：脚本执行引擎（新），将 LLM 输出的 Python 脚本保存到文件后执行

执行策略（两种模式）：

  【脚本模式 — 推荐，默认使用】
  - LLM 输出一个完整的 Python 脚本（用 ```python 包裹）
  - 系统将脚本保存到 outputs/skill_scripts/ 目录
  - 通过读取文件并执行来完成用户请求
  - 优点：无需 JSON/Shell 多层转义，LLM 直接写 Python 代码，错误率极低

  【JSON 任务图模式 — 兼容旧格式】
  - Kahn 算法拓扑排序，将任务分成多个层级（Layer）
  - 同一 Layer 内的任务无依赖关系，用 ThreadPoolExecutor 并行执行
  - Layer 之间顺序执行：等上一层全部完成后才进入下一层
  - 失败传播：依赖失败任务的任务标记为 SKIPPED，不依赖的继续执行

LLM 输出格式（脚本模式，推荐）：
  ```python
  import json, subprocess, webbrowser
  # 步骤1：创建数据文件
  ...
  # 步骤2：运行脚本
  ...
  ```

LLM 输出格式（JSON 模式，兼容）：
  {
    "tasks": [
      {"id": "t1", "title": "...", "command": "...", "depends_on": []},
      {"id": "t2", "title": "...", "command": "...", "depends_on": ["t1"]}
    ]
  }
"""

import os
import re
import sys
import json
import threading
from collections import deque, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.command_executor import execute_command, is_command_safe

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
DIM = "\033[2m"


# ═══════════════════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════════════════

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskNode:
    """任务节点：含依赖关系与执行状态"""
    id: str
    title: str
    command: str = ""
    depends_on: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    layer: int = 0  # 所在执行层级（拓扑排序后赋值）

    @property
    def is_terminal(self) -> bool:
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED)


# ═══════════════════════════════════════════════════════════════════════════════
# 任务图：依赖管理与拓扑分层
# ═══════════════════════════════════════════════════════════════════════════════

class TaskGraph:
    """任务图：管理节点与依赖关系，提供拓扑分层"""

    def __init__(self, goal: str = "未命名任务"):
        self.goal = goal
        self.nodes: Dict[str, TaskNode] = {}
        self._lock = threading.Lock()

    def add_task(self, node: TaskNode) -> None:
        with self._lock:
            self.nodes[node.id] = node

    def get_task(self, task_id: str) -> Optional[TaskNode]:
        return self.nodes.get(task_id)

    @property
    def all_tasks(self) -> List[TaskNode]:
        return list(self.nodes.values())

    @property
    def all_done(self) -> bool:
        return all(t.is_terminal for t in self.nodes.values())

    def validate_dependencies(self) -> List[str]:
        """校验依赖关系：返回错误信息列表（空列表表示无错误）"""
        errors = []
        for task in self.nodes.values():
            for dep in task.depends_on:
                if dep not in self.nodes:
                    errors.append(f"任务 {task.id} 依赖不存在的任务 {dep}")
        return errors

    def detect_cycle(self) -> bool:
        """检测是否存在循环依赖（DFS 三色标记法）"""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in self.nodes}

        def dfs(tid: str) -> bool:
            color[tid] = GRAY
            for dep in self.nodes[tid].depends_on:
                if dep not in self.nodes:
                    continue
                if color[dep] == GRAY:
                    return True  # 回边 → 循环
                if color[dep] == WHITE and dfs(dep):
                    return True
            color[tid] = BLACK
            return False

        return any(dfs(tid) for tid in self.nodes if color[tid] == WHITE)

    def topological_layers(self) -> List[List[TaskNode]]:
        """
        Kahn 算法拓扑排序，返回分层结果。
        同一层的任务之间无依赖关系，可并行执行。
        层与层之间存在依赖，必须顺序执行。

        返回：[[task1, task2], [task3], ...]  每个内层 list 是一个 Layer
        """
        if self.detect_cycle():
            raise ValueError("检测到循环依赖，无法进行拓扑排序")

        # 构建入度表和邻接表（依赖 → 依赖它的任务）
        in_degree = {tid: 0 for tid in self.nodes}
        dependents: Dict[str, List[str]] = defaultdict(list)

        for task in self.nodes.values():
            in_degree[task.id] = len(task.depends_on)
            for dep in task.depends_on:
                if dep in self.nodes:
                    dependents[dep].append(task.id)

        layers: List[List[TaskNode]] = []
        current_layer_ids = [tid for tid, deg in in_degree.items() if deg == 0]
        layer_idx = 0

        while current_layer_ids:
            layer_tasks = [self.nodes[tid] for tid in current_layer_ids]
            for t in layer_tasks:
                t.layer = layer_idx
            layers.append(layer_tasks)

            # 移除当前层节点，更新后继入度
            next_layer_ids = []
            for tid in current_layer_ids:
                for dependent_id in dependents[tid]:
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        next_layer_ids.append(dependent_id)

            current_layer_ids = next_layer_ids
            layer_idx += 1

        return layers

    def get_dependents(self, task_id: str) -> List[str]:
        """获取直接依赖指定任务的后继任务 ID 列表"""
        result = []
        for task in self.nodes.values():
            if task_id in task.depends_on:
                result.append(task.id)
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 显示
# ═══════════════════════════════════════════════════════════════════════════════

def _status_icon(status: TaskStatus) -> str:
    return {
        TaskStatus.COMPLETED: f"{GREEN}☑️{RESET}",
        TaskStatus.RUNNING: "🔄",
        TaskStatus.FAILED: f"{RED}❌{RESET}",
        TaskStatus.SKIPPED: "⏭️",
        TaskStatus.PENDING: "⬜",
    }[status]


def _format_depends(depends_on: List[str]) -> str:
    """格式化依赖标注"""
    if not depends_on:
        return ""
    return f"  {DIM}← depends: {', '.join(depends_on)}{RESET}"


def _graph_lines(graph: TaskGraph) -> List[str]:
    """生成任务图的可视化文本行"""
    lines: List[str] = []
    lines.append("")
    lines.append(f"{CYAN}{'═' * 60}{RESET}")
    lines.append(f"{CYAN}{BOLD}  📋 任务规划：{graph.goal}{RESET}")
    lines.append(f"{CYAN}{'═' * 60}{RESET}")

    # 尝试计算拓扑分层用于显示
    try:
        layers = graph.topological_layers()
        lines.append(f"  {MAGENTA}执行层级：{RESET}")
        for i, layer_tasks in enumerate(layers):
            ids = ", ".join(t.id for t in layer_tasks)
            parallel_hint = f"  {GREEN}⭐并行{RESET}" if len(layer_tasks) > 1 else ""
            lines.append(f"    Layer {i + 1}: {ids}{parallel_hint}")
        lines.append("")
    except ValueError as e:
        lines.append(f"  {RED}层级计算失败：{e}{RESET}")
        lines.append("")

    # 任务详情
    for task in graph.all_tasks:
        icon = _status_icon(task.status)
        hint = ""
        if task.status == TaskStatus.FAILED:
            hint = f"  {RED}(失败){RESET}"
        elif task.status == TaskStatus.SKIPPED:
            hint = f"  {DIM}(跳过){RESET}"
        dep_str = _format_depends(task.depends_on)
        lines.append(f"  {icon} {BOLD}{task.id}{RESET}  {task.title}{hint}{dep_str}")
        if task.command and task.status not in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
            cmd = task.command[:70] + ("…" if len(task.command) > 70 else "")
            lines.append(f"  {DIM}→ {cmd}{RESET}")
        if task.status in (TaskStatus.FAILED, TaskStatus.SKIPPED) and task.result:
            err_line = task.result.split("\n")[-1][:80]
            lines.append(f"  {RED}  ⚠ {err_line}{RESET}")

    # 进度
    done = sum(1 for t in graph.all_tasks if t.status == TaskStatus.COMPLETED)
    total = len(graph.all_tasks)
    lines.append("")
    lines.append(f"  {DIM}进度：{done}/{total}{RESET}")
    lines.append(f"{CYAN}{'═' * 60}{RESET}")
    lines.append("")
    return lines


class LivePlanDisplay:
    """原地刷新任务计划面板（线程安全）"""

    def __init__(self, graph: TaskGraph, *, file=None):
        self.graph = graph
        self._out = file or sys.stdout
        self._height = 0
        self._lock = threading.Lock()

    def update(self, graph: Optional[TaskGraph] = None) -> None:
        with self._lock:
            if graph is not None:
                self.graph = graph
            lines = _graph_lines(self.graph)
            if self._height == 0:
                for line in lines:
                    print(line, file=self._out)
            else:
                self._out.write(f"\033[{self._height}A")
                for line in lines:
                    self._out.write("\033[2K" + line + "\n")
                self._out.flush()
            self._height = len(lines)


def render_graph(graph: TaskGraph, *, file=None) -> None:
    """一次性渲染任务图（非原地刷新）"""
    for line in _graph_lines(graph):
        print(line, file=file or sys.stdout)


# ═══════════════════════════════════════════════════════════════════════════════
# 并行执行引擎
# ═══════════════════════════════════════════════════════════════════════════════

class TaskExecutor:
    """并行执行引擎：按拓扑层执行，同层并行，层间顺序"""

    def __init__(self, cwd: Path, auto_approve: bool = False, max_workers: int = 4):
        self.cwd = cwd
        self.auto_approve = auto_approve
        self.max_workers = max_workers

    def execute(
        self,
        graph: TaskGraph,
        *,
        parallel: bool = True,
        live: bool = True,
        confirm: bool = False,
        on_progress: Optional[Callable] = None,
    ) -> TaskGraph:
        """
        执行任务图。
        - parallel=True：同层任务用 ThreadPoolExecutor 并行
        - parallel=False：同层任务也顺序执行（调试用）
        - live=True：原地刷新显示
        - confirm=True：执行前展示计划等待用户确认
        - on_progress：每次状态变化时的回调
        """
        display = LivePlanDisplay(graph) if live else None

        def refresh():
            if display:
                display.update(graph)
            if on_progress:
                on_progress(graph)

        # 校验
        errors = graph.validate_dependencies()
        if errors:
            for e in errors:
                print(f"{RED}[错误] {e}{RESET}")
            return graph

        if graph.detect_cycle():
            print(f"{RED}[错误] 检测到循环依赖，无法执行{RESET}")
            return graph

        # 确认
        if confirm:
            refresh()
            print(f"{YELLOW}是否执行此任务计划？(输入 y 确认，n 跳过): {RESET}", end="", flush=True)
            try:
                choice = input().strip().lower()
            except (KeyboardInterrupt, EOFError):
                choice = "n"
            if choice != "y":
                print(f"{YELLOW}已跳过执行。{RESET}\n")
                return graph
            self.auto_approve = True  # 确认后自动批准所有子命令

        if not confirm:
            refresh()

        # 拓扑分层
        try:
            layers = graph.topological_layers()
        except ValueError as e:
            print(f"{RED}[错误] {e}{RESET}")
            return graph

        # 逐层执行
        failed_ids: set = set()

        for layer_idx, layer_tasks in enumerate(layers):
            # 过滤掉因前置失败而需跳过的任务
            runnable: List[TaskNode] = []
            for task in layer_tasks:
                if any(dep in failed_ids for dep in task.depends_on):
                    task.status = TaskStatus.SKIPPED
                    task.result = "因前置任务失败而跳过"
                else:
                    runnable.append(task)

            refresh()

            if not runnable:
                continue

            # 执行当前层
            if parallel and len(runnable) > 1:
                self._execute_layer_parallel(runnable, graph, refresh)
            else:
                for task in runnable:
                    self._execute_single(task, graph, refresh)

            # 收集本层失败任务
            for task in runnable:
                if task.status == TaskStatus.FAILED:
                    failed_ids.add(task.id)

            refresh()

        refresh()
        return graph

    def _execute_single(self, task: TaskNode, graph: TaskGraph, refresh: Callable) -> None:
        """执行单个任务"""
        print(f"  [DEBUG] _execute_single: {task.id} '{task.title}'")
        task.status = TaskStatus.RUNNING
        refresh()

        if not task.command:
            task.status = TaskStatus.FAILED
            task.result = "任务未指定 command"
            return

        # 修正 LLM 输出中常见的 python3 -c 引号错误：外层单引号 + 内层双引号 会导致 shell/python 端的引号不匹配。
        # 将形式 python3 -c '..."..."...' -> python3 -c "... '...' ..."
        cmd = task.command.strip()
        if cmd.startswith("python3 -c '") and cmd.endswith("'"):
            inner = cmd[len("python3 -c '"):-1]
            # 把内层双引号替换为单引号以符合本项目约定，减少 SyntaxError 风险
            inner_fixed = inner.replace('"', "'")
            task.command = f'python3 -c "{inner_fixed}"'
            print(f"  [DEBUG] 修正 python3 -c 引号: {cmd} -> {task.command}")

        if not is_command_safe(task.command):
            task.status = TaskStatus.FAILED
            task.result = "命令不符合安全策略，拒绝执行"
            return

        task.result = execute_command(task.command, self.cwd, self.auto_approve, quiet=True)
        if task.result.startswith("⏹") or task.result.startswith("❌") or task.result.startswith("⚠️"):
            task.status = TaskStatus.FAILED
        else:
            task.status = TaskStatus.COMPLETED
        print(f"  [DEBUG] _execute_single 完成: {task.id} → {task.status.value}")

    def _execute_layer_parallel(
        self, tasks: List[TaskNode], graph: TaskGraph, refresh: Callable
    ) -> None:
        """并行执行同一层的多个任务"""
        print(f"  [DEBUG] _execute_layer_parallel: {len(tasks)} 个任务并行")
        for t in tasks:
            t.status = TaskStatus.RUNNING
        refresh()

        def run_task(task: TaskNode) -> None:
            # Delegate to the single-task executor to centralize execution, logging and safety checks.
            # _execute_single will update task.status/result and call refresh as needed.
            self._execute_single(task, graph, refresh)

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as executor:
            futures = {executor.submit(run_task, t): t for t in tasks}
            for future in as_completed(futures):
                future.result()  # 触发异常传播
                refresh()


# ═══════════════════════════════════════════════════════════════════════════════
# 脚本模式：从 LLM 输出提取 Python 脚本并执行（推荐方式）
# ═══════════════════════════════════════════════════════════════════════════════

def extract_python_script(llm_output: str) -> Optional[str]:
    """
    从 LLM 输出中提取 Python 脚本。

    支持以下格式：
      1. ```python ... ``` 代码块（首选）
      2. ```py ... ``` 代码块
      3. 裸 Python 代码（以 import / from / #! 等开头）

    返回纯 Python 代码字符串；未找到则返回 None。
    """
    # 1. 尝试 ```python / ```py 代码块
    m = re.search(r'```(?:python|py)\s*\n(.*?)```', llm_output, re.DOTALL)
    if m:
        return m.group(1).strip()

    # 2. 尝试任意 ``` 代码块（可能是 LLM 没写语言标识）
    m = re.search(r'```\s*\n(.*?)```', llm_output, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        # 只有看起来像 Python 代码才接受
        if _looks_like_python(candidate):
            return candidate

    # 3. 尝试裸代码：找最长的以 Python 关键字开头的段落
    lines = llm_output.strip().splitlines()
    code_lines: List[str] = []
    capturing = False
    for line in lines:
        stripped = line.strip()
        if not capturing:
            if _looks_like_python_line(stripped):
                capturing = True
                code_lines.append(line)
        else:
            # 持续收集直到遇到空行后的非代码内容
            if stripped == "" and code_lines and code_lines[-1].strip() == "":
                break
            code_lines.append(line)

    if code_lines:
        candidate = "\n".join(code_lines).strip()
        if _looks_like_python(candidate):
            return candidate

    return None


def _looks_like_python(text: str) -> bool:
    """快速判断文本是否像 Python 代码"""
    indicators = [
        'import ', 'from ', 'def ', 'class ', 'if __name__',
        'print(', 'json.', 'open(', 'subprocess.', 'Path(',
        'os.', 'sys.', 'webbrowser.', '#!', 'with open',
    ]
    return any(ind in text for ind in indicators)


def _looks_like_python_line(line: str) -> bool:
    """判断单行是否像 Python 代码起点"""
    if not line:
        return False
    if line.startswith('#'):
        return True
    starters = ('import ', 'from ', 'def ', 'class ', 'if ', 'for ', 'while ',
                'with ', 'try:', 'print(', '#!')
    return any(line.startswith(s) for s in starters)


class ScriptExecutor:
    """
    脚本执行引擎：将 LLM 输出的 Python 脚本保存到文件，然后执行。

    流程：
      1. extract_python_script() 从 LLM 响应中提取 Python 代码
      2. 保存到 outputs/skill_scripts/<timestamp>_<slug>.py
      3. 用 subprocess 执行 python <script_path>
      4. 捕获 stdout/stderr 返回结果

    优点：
      - 无需 JSON/Shell 多层转义，LLM 直接写 Python，错误率极低
      - 脚本文件持久化，可复用、可调试
      - Python 原生处理字符串/JSON/文件，无引号嵌套问题
    """

    def __init__(self, cwd: Path, auto_approve: bool = False):
        self.cwd = cwd
        self.auto_approve = auto_approve
        self.scripts_dir = cwd / "outputs" / "skill_scripts"

    def execute(
        self,
        llm_output: str,
        goal: str = "未命名脚本",
        *,
        confirm: bool = False,
    ) -> Dict[str, str]:
        """
        从 LLM 输出提取脚本并执行。

        返回 dict:
          - status: "success" | "failed" | "cancelled" | "no_script"
          - script_path: 保存的脚本路径（如有）
          - stdout: 标准输出
          - stderr: 标准错误
          - returncode: 返回码
          - summary: 人类可读摘要
        """
        script_code = extract_python_script(llm_output)
        if not script_code:
            return {
                "status": "no_script",
                "summary": "LLM 输出中未找到可执行的 Python 脚本",
            }

        # 保存脚本到文件
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r'[^\w\-]', '_', goal[:30]).strip('_') or "skill"
        script_path = self.scripts_dir / f"{timestamp}_{slug}.py"
        script_path.write_text(script_code, encoding="utf-8")
        print(f"{GREEN}[脚本模式] 已保存脚本到：{script_path}{RESET}")

        # 用户确认
        if confirm and not self.auto_approve:
            print(f"\n{CYAN}{'─' * 60}{RESET}")
            print(f"{CYAN}  📜 脚本内容预览：{RESET}")
            print(f"{CYAN}{'─' * 60}{RESET}")
            # 显示前 30 行预览
            preview_lines = script_code.splitlines()[:30]
            for line in preview_lines:
                print(f"  {DIM}{line}{RESET}")
            if len(script_code.splitlines()) > 30:
                print(f"  {DIM}...（共 {len(script_code.splitlines())} 行）{RESET}")
            print(f"{CYAN}{'─' * 60}{RESET}")
            print(f"{YELLOW}是否执行此脚本？(输入 y 确认，n 跳过): {RESET}", end="", flush=True)
            try:
                choice = input().strip().lower()
            except (KeyboardInterrupt, EOFError):
                choice = "n"
            if choice != "y":
                return {
                    "status": "cancelled",
                    "script_path": str(script_path),
                    "summary": "用户取消了脚本执行",
                }
            self.auto_approve = True

        # 执行脚本
        print(f"{GREEN}[脚本模式] 正在执行...{RESET}")
        import subprocess
        try:
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                cwd=str(self.cwd),
                timeout=120,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode == 0:
                status = "success"
                summary = f"✅ 脚本执行成功\n{stdout}" if stdout else "✅ 脚本执行成功（无输出）"
                print(f"{GREEN}[脚本模式] 执行成功{RESET}")
                if stdout:
                    print(f"{DIM}{stdout[:500]}{RESET}")
            else:
                status = "failed"
                summary = f"❌ 脚本执行失败 (返回码 {result.returncode})\n{stderr or stdout}"
                print(f"{RED}[脚本模式] 执行失败 (返回码 {result.returncode}){RESET}")
                if stderr:
                    print(f"{RED}{stderr[:500]}{RESET}")

            # 执行完成后删除临时脚本文件
            _cleanup_script(script_path)

            return {
                "status": status,
                "script_path": str(script_path),
                "stdout": stdout,
                "stderr": stderr,
                "returncode": str(result.returncode),
                "summary": summary,
            }
        except subprocess.TimeoutExpired:
            msg = "❌ 脚本执行超时（超过 120 秒）"
            print(f"{RED}{msg}{RESET}")
            _cleanup_script(script_path)
            return {
                "status": "failed",
                "script_path": str(script_path),
                "summary": msg,
            }
        except Exception as e:
            msg = f"❌ 脚本执行异常：{e}"
            print(f"{RED}{msg}{RESET}")
            _cleanup_script(script_path)
            return {
                "status": "failed",
                "script_path": str(script_path),
                "summary": msg,
            }


def _cleanup_script(script_path: Path) -> None:
    """安全删除临时脚本文件"""
    try:
        if script_path.exists():
            script_path.unlink()
            print(f"{DIM}[脚本模式] 已清理临时文件：{script_path}{RESET}")
    except Exception:
        pass  # 删除失败不影响主流程


def format_script_summary(result: Dict[str, str]) -> str:
    """生成脚本执行摘要"""
    status = result.get("status", "unknown")
    if status == "no_script":
        return "⚠️ 未找到可执行脚本"
    if status == "cancelled":
        return "⏹ 用户取消执行"

    lines = [f"📜 脚本执行{ '完成' if status == 'success' else '失败'}"]
    if result.get("script_path"):
        lines.append(f"   脚本路径：{result['script_path']}")
    if result.get("stdout"):
        lines.append(f"   输出：{result['stdout'][:200]}")
    if result.get("stderr") and status == "failed":
        lines.append(f"   错误：{result['stderr'][:200]}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 计划解析
# ═══════════════════════════════════════════════════════════════════════════════

def parse_plan_from_json(llm_output: str, goal: str = "未命名任务") -> TaskGraph:
    """
    从 LLM 输出中解析 JSON 格式的任务计划。
    支持容错：正则提取 JSON 块 → json.loads → 构建 TaskGraph。

    期望格式：
    {
      "tasks": [
        {"id": "t1", "title": "...", "command": "...", "depends_on": []},
        {"id": "t2", "title": "...", "command": "...", "depends_on": ["t1"]}
      ]
    }
    """
    # 尝试提取 JSON 块（可能被 ```json ... ``` 包裹）
    json_text = _extract_json_block(llm_output)
    if not json_text:
        raise ValueError("LLM 输出中未找到有效的 JSON 任务计划")

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败：{e}")

    if not isinstance(data, dict) or "tasks" not in data:
        raise ValueError("JSON 缺少 tasks 字段")

    graph = TaskGraph(goal=goal)
    for idx, task_data in enumerate(data["tasks"], 1):
        task_id = task_data.get("id", f"t{idx}")
        title = task_data.get("title", f"步骤 {idx}")
        command = task_data.get("command", "")
        depends_on = task_data.get("depends_on", [])
        if not isinstance(depends_on, list):
            depends_on = [depends_on] if depends_on else []
        # 清理命令中的 markdown 反引号
        command = re.sub(r'^`+|`+$', '', command.strip())
        graph.add_task(TaskNode(
            id=str(task_id),
            title=str(title),
            command=str(command),
            depends_on=[str(d) for d in depends_on],
        ))

    print(f"  [DEBUG] parse_plan_from_json: goal='{goal}', {len(graph.nodes)} 个任务")
    for t in graph.all_tasks:
        dep_str = f", depends_on={t.depends_on}" if t.depends_on else ""
        print(f"  [DEBUG]   {t.id}: {t.title}{dep_str}")
    return graph


def _extract_json_block(text: str) -> Optional[str]:
    """从文本中提取 JSON 块，支持 ```json 包裹和裸 JSON"""
    # 尝试 ```json ... ``` 包裹
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        return m.group(1).strip()

    # 尝试提取 { ... } 块（贪婪匹配最外层）
    start = text.find('{')
    if start == -1:
        return None
    # 括号感知匹配
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


# ── 兼容旧格式：[EXEC: ...] 标记 ──────────────────────────────────────────────

_EXEC_START = re.compile(r'\[EXEC:\s*')


def _extract_exec_commands(text: str) -> List[str]:
    """括号感知提取 [EXEC: ...]，正确处理命令内部的 [...] 列表语法"""
    commands: List[str] = []
    for m in _EXEC_START.finditer(text):
        i = m.end()
        depth = 1
        while i < len(text) and depth > 0:
            ch = text[i]
            if ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    break
            elif ch in ('"', "'"):
                quote = ch
                i += 1
                while i < len(text) and text[i] != quote:
                    if text[i] == '\\':
                        i += 1
                    i += 1
            i += 1
        commands.append(text[m.end():i].strip())
    return commands


def parse_plan_from_exec_tags(llm_output: str, goal: str = "未命名任务") -> TaskGraph:
    """
    兼容旧格式：从 [EXEC: ...] 标记构建顺序任务图（每个任务依赖前一个）。
    当 JSON 解析失败时作为回退方案。
    """
    raw_commands = _extract_exec_commands(llm_output)
    if not raw_commands:
        raise ValueError("LLM 响应中未找到 [EXEC: ...] 命令，无法生成任务计划")

    graph = TaskGraph(goal=goal)
    prev_id = None
    for idx, cmd in enumerate(raw_commands, 1):
        cmd = re.sub(r'^`+|`+$', '', cmd).strip()
        task_id = f"t{idx}"
        depends = [prev_id] if prev_id else []
        graph.add_task(TaskNode(
            id=task_id,
            title=f"步骤 {idx}",
            command=cmd,
            depends_on=depends,
        ))
        prev_id = task_id

    print(f"  [DEBUG] parse_plan_from_exec_tags (兼容模式): {len(graph.nodes)} 个顺序任务")
    return graph


def parse_plan(llm_output: str, goal: str = "未命名任务") -> TaskGraph:
    """
    智能解析：优先尝试 JSON 格式，失败则回退到 [EXEC] 标记格式。
    """
    print(f"  [DEBUG] LLM输出: {llm_output}")
    try:
        return parse_plan_from_json(llm_output, goal)
    except ValueError as json_err:
        print(f"  [DEBUG] JSON 解析失败（{json_err}），尝试 [EXEC] 兼容格式")
        return parse_plan_from_exec_tags(llm_output, goal)


# ═══════════════════════════════════════════════════════════════════════════════
# LLM 提示词
# ═══════════════════════════════════════════════════════════════════════════════

BUILD_PLAN_PROMPT = """
## 技能说明
{skill_detail}

本技能所在目录为 `skills/{skill_folder}/`，请将说明中的 `{{baseDir}}` 替换为此路径。
脚本路径示例：`skills/{skill_folder}/scripts/main.ts`

请严格按照上述技能说明中的"执行流程"逐步完成用户请求。
你需要输出一个 **JSON 格式的任务计划**，系统会根据任务间的依赖关系自动并行执行无依赖的任务。

## 输出格式要求

请输出如下 JSON 格式（用 ```json 包裹）：

```json
{{
  "tasks": [
    {{
      "id": "t1",
      "title": "步骤简述",
      "command": "要执行的 shell 命令",
      "depends_on": []
    }},
    {{
      "id": "t2",
      "title": "步骤简述",
      "command": "要执行的 shell 命令",
      "depends_on": ["t1"]
    }}
  ]
}}
```

## 字段说明

- `id`：任务唯一标识，格式为 t1, t2, t3...
- `title`：该步骤的简短描述（不超过 30 字）
- `command`：要执行的 shell 命令（单条命令，不要用 && 连接多条）
- `depends_on`：本任务依赖的前置任务 id 列表
  - `[]` 表示无依赖，可与同层其他无依赖任务**并行执行**
  - `["t1"]` 表示必须等 t1 完成后才能执行
  - `["t1", "t2"]` 表示必须等 t1 和 t2 都完成后才能执行

## 依赖关系设计原则

1. 如果步骤 B 需要使用步骤 A 生成的文件，则 B 的 depends_on 应包含 A
2. 如果两个步骤互不依赖（如分别生成不同文件），可设为同层并行（depends_on 都为空或相同）
3. 最后一步通常是"打开预览"，应依赖所有生成步骤

## 命令安全要求

- 首词仅限：python, python3, node, bash, sh, echo, open, mkdir, cat, bun, cp, mv, ls
- 写入 JSON 数据文件时，必须用 python3 -c 调用 json.dump：
  [EXEC: python3 -c "import json; data={{'word':'...'}}; json.dump(data, open('path/file.json','w'), indent=2, ensure_ascii=False)"]
- python3 -c 外层用双引号，内部字符串用单引号
- 不要使用绝对路径、管道、分号、反引号

## 示例

用户请求：为单词 crazy 制作闪卡

```json
{{
  "tasks": [
    {{
      "id": "t1",
      "title": "创建 crazy.json 数据文件",
      "command": "python3 -c \\"import json; data={{'word':'crazy','phonetic':'/ˈkreɪzi/','pos':'adj.','definition':'疯狂的','examples':[{{'en':'He is crazy about music.','zh':'他对音乐疯狂。'}},{{'en':'That was a crazy idea.','zh':'那是个疯狂的想法。'}},{{'en':'She drives me crazy.','zh':'她让我发疯。'}}],'synonyms':['mad','insane','wild','nuts']}}; json.dump(data, open('skills/flash-card/data/crazy.json','w'), indent=2, ensure_ascii=False)\\"",
      "depends_on": []
    }},
    {{
      "id": "t2",
      "title": "生成 HTML 闪卡",
      "command": "python skills/flash-card/scripts/make_flashcard.py skills/flash-card/data/crazy.json",
      "depends_on": ["t1"]
    }},
    {{
      "id": "t3",
      "title": "打开预览",
      "command": "open crazy.html",
      "depends_on": ["t2"]
    }}
  ]
}}
```

用户请求：{user_input}

请直接输出 JSON 任务计划（用 ```json 包裹），不要输出其他解释文字：
"""


def build_plan_prompt(skill_name: str, skill_detail: str, user_input: str, skill_folder: str = "") -> str:
    return BUILD_PLAN_PROMPT.format(
        skill_detail=skill_detail,
        skill_folder=skill_folder or skill_name,
        user_input=user_input,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 脚本模式 Prompt（推荐）：LLM 输出 Python 脚本 → 保存文件 → 执行 → 删除文件
# ═══════════════════════════════════════════════════════════════════════════════

BUILD_SCRIPT_PROMPT = """
## 技能说明
{skill_detail}

本技能所在目录为 `skills/{skill_folder}/`，请将说明中的 `{{baseDir}}` 替换为此路径。
脚本路径示例：`skills/{skill_folder}/scripts/main.ts`

请严格按照上述技能说明中的"执行流程"逐步完成用户请求。
你需要输出一个 **完整的 Python 脚本**，系统会将其保存到文件并执行。

## 输出格式要求

请用 ```python 代码块包裹你的 Python 脚本：

```python
import json
import subprocess
import webbrowser
from pathlib import Path

# 步骤1：创建数据文件
data = {{"word": "crazy", "phonetic": "/ˈkreɪzi/", ...}}
Path("skills/flash-card/data/crazy.json").write_text(
    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
)

# 步骤2：运行脚本
subprocess.run(
    ["python", "skills/flash-card/scripts/make_flashcard.py", "skills/flash-card/data/crazy.json"],
    check=True
)

# 步骤3：打开预览
webbrowser.open("crazy.html")

print("✅ 闪卡生成完成！")
```

## 脚本编写要求

1. **使用 Python 标准库**：import json, subprocess, webbrowser, pathlib 等，不要依赖未安装的第三方包
2. **使用 Path().write_text()** 写入 JSON 数据文件，比 python3 -c 干净得多
3. **subprocess.run([...], check=True)** 调用外部脚本时使用列表形式（不用 shell 字符串）
4. **最后一步用 webbrowser.open()** 打开生成的文件预览
5. **print() 输出关键步骤**，方便用户了解进度
6. **所有路径使用相对路径**（相对于项目根目录），不要用绝对路径
7. **字符串中避免使用反斜杠转义**，需要时用原始字符串 r"..." 或正斜杠

## 示例

用户请求：为单词 crazy 制作闪卡

```python
import json
import subprocess
import webbrowser
from pathlib import Path

# 确保数据目录存在
Path("skills/flash-card/data").mkdir(parents=True, exist_ok=True)

# 创建单词数据文件
data = {{
    "word": "crazy",
    "phonetic": "/ˈkreɪzi/",
    "pos": "adj.",
    "definition": "疯狂的；狂热的，着迷的",
    "examples": [
        {{"en": "He is crazy about music.", "zh": "他对音乐非常狂热。"}},
        {{"en": "That was a crazy idea.", "zh": "那是个疯狂的想法。"}},
        {{"en": "The crowd went crazy when the band appeared.", "zh": "乐队出现时，人群疯狂了。"}}
    ],
    "synonyms": ["mad", "insane", "wild", "nuts", "fanatical", "zealous"]
}}
json_path = Path("skills/flash-card/data/crazy.json")
json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"✅ 已创建数据文件：{{json_path}}")

# 生成 HTML 闪卡
result = subprocess.run(
    ["python", "skills/flash-card/scripts/make_flashcard.py", str(json_path)],
    capture_output=True, text=True
)
if result.returncode != 0:
    print(f"❌ 脚本执行失败：{{result.stderr}}")
    exit(1)
print(result.stdout.strip())

# 打开预览
html_path = Path("crazy.html")
if html_path.exists():
    webbrowser.open(str(html_path.absolute()))
    print(f"✅ 已打开预览：{{html_path}}")
```

用户请求：{user_input}

请直接输出 Python 脚本（用 ```python 包裹），不要输出其他解释文字：
"""


def build_script_prompt(skill_name: str, skill_detail: str, user_input: str, skill_folder: str = "") -> str:
    """构建脚本模式的 LLM 提示词"""
    return BUILD_SCRIPT_PROMPT.format(
        skill_detail=skill_detail,
        skill_folder=skill_folder or skill_name,
        user_input=user_input,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 摘要
# ═══════════════════════════════════════════════════════════════════════════════

def format_plan_summary(graph: TaskGraph) -> str:
    """生成任务执行摘要"""
    lines = [f"📋 任务「{graph.goal}」执行完成"]
    for t in graph.all_tasks:
        icon = _status_icon(t.status)
        lines.append(f"{icon} {t.id} {t.title}")
        if t.result:
            lines.append(f"   {t.result.split(chr(10))[0][:120]}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 演示
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 演示：构建一个含并行结构的任务图
    graph = TaskGraph(goal="演示任务图")

    # Layer 1: t1（无依赖）
    graph.add_task(TaskNode(id="t1", title="创建数据文件", command="echo 'data'", depends_on=[]))
    # Layer 2: t2, t3（都依赖 t1，可并行）
    graph.add_task(TaskNode(id="t2", title="生成HTML", command="echo 'html'", depends_on=["t1"]))
    graph.add_task(TaskNode(id="t3", title="复制到输出", command="echo 'copy'", depends_on=["t1"]))
    # Layer 3: t4（依赖 t2 和 t3）
    graph.add_task(TaskNode(id="t4", title="打开预览", command="echo 'open'", depends_on=["t2", "t3"]))

    print(f"{MAGENTA}=== 拓扑分层演示 ==={RESET}")
    layers = graph.topological_layers()
    for i, layer in enumerate(layers):
        ids = [t.id for t in layer]
        print(f"  Layer {i + 1}: {ids}")

    print(f"\n{MAGENTA}=== 任务图渲染 ==={RESET}")
    render_graph(graph)

    print(f"{MAGENTA}=== JSON 解析演示 ==={RESET}")
    sample_json = '''```json
{
  "tasks": [
    {"id": "t1", "title": "步骤1", "command": "echo hello", "depends_on": []},
    {"id": "t2", "title": "步骤2", "command": "echo world", "depends_on": ["t1"]}
  ]
}
```'''
    parsed = parse_plan_from_json(sample_json, goal="JSON解析测试")
    render_graph(parsed)

    print(f"{YELLOW}（演示模式，不实际执行。运行 agent.py 体验完整流程）{RESET}")