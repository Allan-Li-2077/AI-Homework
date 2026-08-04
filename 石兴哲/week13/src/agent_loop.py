"""
渐进式 Skill 加载 Harness — CLI Agent Loop

教学重点：
  1. Function-calling 驱动的渐进加载：LLM 决定何时加载 skill，不是硬编码规则
  2. 三层加载：
     Level 0 — 启动时扫描 frontmatter（~100 tokens/skill）
     Level 1 — LLM 判断相关后 load_skill() 加载完整 SKILL.md
     Level 2 — SKILL.md 引用脚本/参考文件时，LLM 通过 read_file/run_command 进一步加载
  3. 每次 tool call 都打印加载日志，让学生看到渐进过程

工具说明（注册给 LLM 的 3 个 function）：
  - load_skill: 加载指定 skill 的完整 SKILL.md body（渐进加载的核心）
  - read_file:  读取任意文件（skill 引用的参考文档、脚本源码等）
  - run_command: 执行命令（skill 定义的脚本、分析流水线等）

使用方式：
  python src/agent_loop.py

命令：
  /skills   查看当前 skill catalog 和加载状态
  /reset    卸载所有已加载的 skill，回到初始状态
  /help     显示帮助
  /exit     退出

依赖：
  pip install openai pyyaml
  设置 DEEPSEEK_API_KEY 环境变量
"""

import os
import sys
import json
import subprocess
import logging
from pathlib import Path

# 让 src/ 内的模块可以相互 import
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm_config import get_chat_client, current_model_info
from src.skill_loader import SkillLoader, DEFAULT_SKILLS_DIR

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ── 终端颜色 ───────────────────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
DIM = "\033[2m"

# ── Agent 的 System Prompt ─────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """你是一个具有渐进式 Skill 加载能力的 AI 助手。

## 核心机制：渐进式 Skill 加载

你拥有一组可用的 Skill，但为了节省 context，启动时只加载了它们的**名称和简介**（frontmatter）。
当你判断某个 Skill 与用户的任务相关时，**先调用 load_skill 加载它的完整内容**，然后再根据其指令行动。

这就像你先扫一眼书架上的书名，确定需要哪本书之后，才拿下来翻看里面的具体章节。

## 当前可用的 Skill（仅 frontmatter 摘要）

{skill_catalog}

## 可用的工具

你有以下工具可以调用：

1. **load_skill(name)**
   - 加载指定 Skill 的完整 SKILL.md 内容
   - **重要**：在需要使用某个 Skill 之前，必须先调用此工具
   - 加载后的内容会追加到当前对话中，之后你可以根据其指令执行任务

2. **read_file(path)**
   - 读取任意文件的完整内容
   - 用于读取 Skill 中引用的参考文档、脚本源码、配置文件等
   - path 可以是绝对路径或相对于项目根目录的相对路径

3. **run_command(command)**
   - 执行一条 shell 命令并返回输出
   - 用于运行 Skill 中定义的脚本、分析流水线等
   - 命令会在项目根目录下执行

## 工作流程

1. 用户提出任务
2. 你浏览 skill catalog（上面已列出），判断哪些 skill 可能相关
3. 调用 load_skill 加载相关的 skill 完整内容
4. 根据 skill 的指令，可能需要进一步 read_file（读参考文档/脚本）或 run_command（执行脚本）
5. 完成任务，向用户汇报结果

## 注意事项
- 不要假设 skill 的内容——必须 load_skill 之后才能知道具体指令
- 用户看不到 skill catalog，他们只知道大致有哪些能力
- 如果一个 skill 用不上，就不要加载它，节省 context
- 优先用中文回复"""


# ── Tool 定义（发送给 LLM）─────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "加载指定 Skill 的完整 SKILL.md 内容。在需要使用某个 Skill 的具体指令之前必须先调用此函数。每次只加载一个 skill。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill 的名称（来自 skill catalog 中的 name 字段），例如 'code-review'",
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取任意文件的完整内容。用于读取 Skill 中引用的参考文档、脚本源码、配置文件等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件的路径，可以是绝对路径或相对于项目根目录的路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "执行一条命令并返回 stdout 和 stderr 输出。用于运行 Skill 中定义的脚本或命令。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 shell 命令",
                    }
                },
                "required": ["command"],
            },
        },
    },
]


# ── Tool 执行器 ─────────────────────────────────────────────────────────────────

class ToolExecutor:
    """在本地执行 LLM 请求的 tool_call，返回结果字符串"""

    def __init__(self, loader: SkillLoader, project_root: Path):
        self.loader = loader
        self.project_root = project_root

    def execute(self, tool_name: str, arguments: dict) -> str:
        if tool_name == "load_skill":
            return self._load_skill(arguments.get("name", ""))
        elif tool_name == "read_file":
            return self._read_file(arguments.get("path", ""))
        elif tool_name == "run_command":
            return self._run_command(arguments.get("command", ""))
        else:
            return f"[错误] 未知工具：{tool_name}"

    def _load_skill(self, name: str) -> str:
        if not name:
            return "[错误] load_skill 需要 name 参数"
        # 检查是否已加载
        if self.loader.is_loaded(name):
            return f"[信息] Skill '{name}' 已经加载过了，无需重复加载。"
        content = self.loader.load_full(name)
        if content is None:
            available = ", ".join(self.loader.get_skill_names())
            return f"[错误] Skill '{name}' 不存在。可用 skill：{available}"
        return content

    def _read_file(self, path: str) -> str:
        if not path:
            return "[错误] read_file 需要 path 参数"
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = self.project_root / file_path
        if not file_path.exists():
            return f"[错误] 文件不存在：{file_path}"
        try:
            content = file_path.read_text(encoding="utf-8")
            return f"=== {file_path.name} ===\n{content}"
        except Exception as e:
            return f"[错误] 读取文件失败：{e}"

    def _run_command(self, command: str) -> str:
        if not command:
            return "[错误] run_command 需要 command 参数"
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.project_root),
            )
            out = result.stdout.strip()
            err = result.stderr.strip()
            parts = []
            if out:
                parts.append(f"[stdout]\n{out}")
            if err:
                parts.append(f"[stderr]\n{err}")
            if not parts:
                parts.append(f"[exit code: {result.returncode}]（无输出）")
            return "\n".join(parts)
        except subprocess.TimeoutExpired:
            return "[错误] 命令执行超时（30 秒）"
        except Exception as e:
            return f"[错误] 命令执行失败：{e}"


# ── Agent 主循环 ────────────────────────────────────────────────────────────────

def print_banner(model_info: dict, catalog_count: int):
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  渐进式 Skill 加载 Harness{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")
    print(f"  模型：{CYAN}{model_info['display']}{RESET}")
    print(f"  已扫描 skill：{GREEN}{catalog_count}{RESET} 个（仅 frontmatter）")
    print(f"  {DIM}切换模型：LLM_PROVIDER=deepseek 或 qwen{RESET}")
    print(f"\n  {DIM}输入 /skills、/reset、/help、/exit 查看功能{RESET}")
    print(f"{BOLD}{'='*60}{RESET}\n")


def print_tool_call(tool_name: str, args: dict):
    """打印 tool call 的加载日志"""
    icon = {"load_skill": "📥", "read_file": "📄", "run_command": "⚡"}.get(tool_name, "🔧")
    if tool_name == "load_skill":
        print(f"\n  {YELLOW}{icon} [渐进加载] 正在加载 skill：{args.get('name', '?')}{RESET}")
    elif tool_name == "read_file":
        fname = Path(args.get("path", "")).name
        print(f"  {YELLOW}{icon} [渐进加载] 读取文件：{fname}{RESET}")
    elif tool_name == "run_command":
        cmd = args.get("command", "")[:60]
        print(f"  {YELLOW}{icon} [渐进加载] 执行命令：{cmd}{RESET}")


def main():
    # ── 初始化 ─────────────────────────────────────────────────────────────
    model_info = current_model_info()
    project_root = Path(__file__).parent.parent

    # 检查 API Key
    try:
        client, model = get_chat_client()
    except EnvironmentError as e:
        print(f"{YELLOW}{e}{RESET}")
        print("请设置环境变量：$env:DEEPSEEK_API_KEY = \"sk-xxx\"")
        sys.exit(1)

    # 渐进式加载 Level 0：只扫描 frontmatter
    loader = SkillLoader()
    catalog = loader.scan_catalog()
    if not catalog:
        print(f"{YELLOW}警告：skills/ 目录下未找到任何 SKILL.md 文件{RESET}")
        print("请在 skills/<skill-name>/SKILL.md 创建至少一个 skill")
        sys.exit(1)

    executor = ToolExecutor(loader, project_root)
    print_banner(model_info, len(catalog))

    # ── 构建初始 System Prompt（仅含 catalog frontmatter）──────────────────
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        skill_catalog=loader.get_catalog_text()
    )

    messages: list[dict] = [
        {"role": "system", "content": system_prompt}
    ]

    # ── 对话循环 ───────────────────────────────────────────────────────────
    while True:
        try:
            user_input = input(f"{BOLD}你：{RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            user_input = "/exit"

        if not user_input:
            continue

        # ── 内置命令 ────────────────────────────────────────────────
        if user_input == "/exit":
            print("再见！")
            break

        if user_input == "/skills":
            _print_skill_status(loader)
            continue

        if user_input == "/reset":
            _reset_loader(loader)
            # 重建 system prompt
            system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                skill_catalog=loader.get_catalog_text()
            )
            messages = [{"role": "system", "content": system_prompt}]
            continue

        if user_input == "/help":
            _print_help()
            continue

        # ── 正常对话：追加用户消息 ─────────────────────────────────
        messages.append({"role": "user", "content": user_input})

        # ── Agent Loop：反复调用 LLM 直到不再请求 tool ────────────
        while True:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                temperature=0.7,
                stream=True,
            )

            # 收集流式响应（处理 tool_calls 的流式拼接）
            content_chunks: list[str] = []
            tool_calls_map: dict[int, dict] = {}  # index → {id, name, args_str}

            for chunk in stream:
                delta = chunk.choices[0].delta

                # 文本内容
                if delta.content:
                    content_chunks.append(delta.content)
                    print(delta.content, end="", flush=True)

                # Tool calls（流式拼接）
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {
                                "id": tc.id or "",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.id:
                            tool_calls_map[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_map[idx]["function"]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_map[idx]["function"]["arguments"] += tc.function.arguments

            # 如果有文本输出，换行
            if content_chunks:
                print()

            # 没有 tool call → 本轮完成
            if not tool_calls_map:
                # 将 assistant 回复加入 messages
                full_content = "".join(content_chunks)
                messages.append({"role": "assistant", "content": full_content})
                break

            # 有 tool call → 先添加 assistant 消息（含 tool_calls）
            tool_calls_formatted = []
            for idx in sorted(tool_calls_map.keys()):
                tc = tool_calls_map[idx]
                tool_calls_formatted.append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                })

            full_content = "".join(content_chunks) if content_chunks else None
            assistant_msg = {"role": "assistant", "content": full_content} if full_content else {"role": "assistant"}
            assistant_msg["tool_calls"] = tool_calls_formatted
            messages.append(assistant_msg)

            # 执行每个 tool call
            for tc in tool_calls_formatted:
                tool_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                print_tool_call(tool_name, args)
                result = executor.execute(tool_name, args)

                # 将 tool 结果加入 messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            # 继续循环，LLM 可能会再次调用 tool 或给出最终回复
            print(f"  {DIM}[继续处理...]{RESET}\n")
            print(f"{GREEN}Muse：{RESET}", end="", flush=True)


def _print_skill_status(loader: SkillLoader):
    """/skills 命令：打印当前 skill 加载状态"""
    print(f"\n{CYAN}{'─'*50}{RESET}")
    print(f"{CYAN}  Skill 加载状态{RESET}")
    print(f"{CYAN}{'─'*50}{RESET}")
    for info in loader._catalog:
        icon = "📥" if info.body_loaded else "📦"
        status = f"{GREEN}已加载{RESET}" if info.body_loaded else f"{DIM}未加载{RESET}"
        print(f"  {icon} {BOLD}{info.name}{RESET} — {status}")
        print(f"     {info.description[:80]}")
    print(f"{CYAN}{'─'*50}{RESET}\n")


def _reset_loader(loader: SkillLoader):
    """/reset 命令：卸载所有已加载 skill，重新扫描"""
    loader._catalog = []
    loader._by_name = {}
    loader.scan_catalog()
    print(f"\n{GREEN}已卸载所有 skill，catalog 重新扫描（仅 frontmatter）。{RESET}\n")


def _print_help():
    print(f"""
{CYAN}可用命令：{RESET}
  /skills   查看所有 skill 的加载状态（已加载/未加载）
  /reset    卸载所有已加载的 skill，回到初始状态
  /help     显示此帮助
  /exit     退出

{CYAN}渐进加载说明：{RESET}
  1. 启动时只加载 frontmatter（name + description），不占 context
  2. 对话中 LLM 判断某 skill 相关 → 自动调用 load_skill 加载完整内容
  3. Skill 引用的脚本/参考文件 → LLM 再调用 read_file 进一步加载
""")





if __name__ == "__main__":
    main()
