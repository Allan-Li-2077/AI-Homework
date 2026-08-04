"""
Skill Agent —— 渐进式 Skill 加载的对话 Agent

在 react_function_calling_multiturn.py基础上进行修改

渐进式加载流程：
  L1 发现：启动时 scan_skills()，仅读 frontmatter，打印摘要清单
  L2 路由：每轮对话，system prompt 含 skill 摘要，LLM 判断是否激活
  L3 注入：激活后将完整 SKILL.md 注入下一轮 system prompt，用完即释
"""

import os
import re
import sys
import json
import time
import logging
import argparse
import subprocess
import tempfile
from pathlib import Path
from typing import Generator

from openai import OpenAI

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent))

from skill_loader import (
    SkillInfo,
    scan_skills,
    get_skill_index_prompt,
    build_skill_system_prompt,
    load_reference,
    list_references,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── LLM 配置（兼容 DeepSeek / DashScope，与 react_function_calling_multiturn.py 同构）────

def _build_client() -> tuple[OpenAI, str]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        return (
            OpenAI(api_key=api_key, base_url="https://api.deepseek.com"),
            os.getenv("AGENT_MODEL", "deepseek-v4-flash"),
        )
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if api_key:
        return (
            OpenAI(api_key=api_key,
                   base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
            os.getenv("AGENT_MODEL", "qwen3.7-plus"),
        )
    raise EnvironmentError(
        "请设置环境变量 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY\n"
        "  Windows PowerShell: $env:DEEPSEEK_API_KEY='sk-xxx'"
    )

client, MODEL = _build_client()

# ── System Prompt 构建 ─────────────────────────────────────────────────────────

AGENT_BASE_PROMPT = """你是一个智能助手，能够按用户请求激活并使用各种技能（Skill）。
运行环境：Windows 系统，使用 cmd 解释器。

## 工作规则
1. 收到用户请求后，从下方技能清单中判断是否有匹配的技能
2. 若匹配：仅输出一行激活标记 skill_activated:<技能名称>，不要输出其他内容
3. 激活标记输出后，系统会自动加载完整技能指令，届时你必须用 ```python 代码块写出执行代码，系统会自动执行
4. 绝对不要询问用户是否允许执行——直接执行，不要等待许可
5. 若无匹配技能：作为通用助手直接回答
6. 用户可能在同一会话中连续使用技能，注意结合历史上下文
"""


def _make_system_prompt(skills: list[SkillInfo], active_skill: SkillInfo | None) -> str:
    """
    构建当前轮的 system prompt：
    - 无激活 skill：基础人设 + skill 摘要清单（L1）
    - 有激活 skill：基础人设 + 完整 SKILL.md（L3）
    """
    parts = [AGENT_BASE_PROMPT]

    if active_skill is None:
        parts.append("## 可用技能清单\n" + get_skill_index_prompt(skills))
    else:
        parts.append(build_skill_system_prompt(active_skill))

    return "\n\n".join(parts)


# ── 会话管理（与 react_function_calling_multiturn.py 对齐）───────────────────────

def new_session(skills: list[SkillInfo]) -> list:
    """创建一份全新的多轮对话历史（只含 system prompt，无激活 skill）"""
    return [{"role": "system", "content": _make_system_prompt(skills, None)}]


# ── 激活标记解析 ────────────────────────────────────────────────────────────────

_ACTIVATION_RE = re.compile(r"skill_activated:\s*([^\s\n]+)")


def _parse_activation(text: str, skills: list[SkillInfo]) -> SkillInfo | None:
    """从 LLM 回复文本中解析 skill_activated:<name> 标记"""
    m = _ACTIVATION_RE.search(text)
    if not m:
        return None
    name = m.group(1).strip()
    for s in skills:
        if s.name == name:
            return s
    logger.warning(f"LLM 激活了未知 skill: {name}")
    return None


def _strip_activation(text: str) -> str:
    """从回复正文中移除激活标记行，不让用户看到"""
    return _ACTIVATION_RE.sub("", text).strip()


# ── 脚本执行 ────────────────────────────────────────────────────────────────────

def _extract_and_run_scripts(text: str, skill: SkillInfo, timeout: int = 30) -> str:
    """
    从 LLM 回复中提取代码块并执行。
    """
    skill_dir = skill.base_dir
    parent_path = str(skill.base_dir.parent).replace("\\", "/")

    # 匹配代码块，捕获语言标签和内容
    code_blocks = re.findall(
        r'```(python|bash|sh|cmd)\s*\n(.*?)```', text, re.DOTALL
    )
    if not code_blocks:
        logger.info("未找到代码块")
        return ""

    logger.info(f"找到 {len(code_blocks)} 个代码块: {[lang for lang, _ in code_blocks]}")

    results = []
    for lang, code in code_blocks:
        code = code.strip()
        if not code:
            continue

        # 路径修正：仅替换 SKILL.md 中的示例路径，不破坏 Python 转义
        code = code.replace(".cursor/skills/", f"{parent_path}/")

        try:
            if lang == "python":
                # 替换 LLM 代码中的 subprocess.run(["python", ...]) 为正确的解释器路径
                code = code.replace(
                    'subprocess.run(["python",',
                    f'subprocess.run([r"{sys.executable}",'
                )

                logger.info(f"执行 Python 代码块（{len(code)} 字符）")
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False, encoding="utf-8",
                    dir=str(skill_dir),
                ) as tmp:
                    tmp.write(code)
                    tmp_path = tmp.name

                try:
                    proc = subprocess.run(
                        [sys.executable, tmp_path],
                        capture_output=True, text=True,
                        timeout=timeout, cwd=str(skill_dir),
                        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    )
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

            else:
                # bash/sh/cmd 代码块：直接通过 shell 执行
                logger.info(f"执行 Shell 命令: {code[:120]}")
                proc = subprocess.run(
                    code, shell=True,
                    capture_output=True, text=True,
                    timeout=timeout, cwd=str(skill_dir),
                )

            out = proc.stdout.strip()
            err = proc.stderr.strip()
            logger.info(f"执行结果: returncode={proc.returncode}, "
                        f"stdout={out[:200] if out else '(空)'}, "
                        f"stderr={err[:200] if err else '(空)'}")
            if proc.returncode == 0:
                results.append(f"[执行成功]\n{out}" if out else "[执行成功，无输出]")
            else:
                results.append(f"[执行失败，exit={proc.returncode}]\n{err}")
        except subprocess.TimeoutExpired:
            results.append(f"[超时 {timeout}s] {lang} 代码块")
        except Exception as e:
            results.append(f"[异常] {e}")

    return "\n\n".join(results)


# ── 核心 run()：generator，与 react_function_calling_multiturn.py 同构 ──────────

def run(
    question: str,
    skills: list[SkillInfo],
    max_steps: int = 10,
    history: list | None = None,
    active_skill: SkillInfo | None = None,
) -> Generator[dict, None, SkillInfo | None]:
    """
    执行 Skill Agent 循环，yield 每步结构化结果。

    与 react_function_calling_multiturn.py 的 run() 对比：
      - 相同：history 多轮复用，yield step_data 字典，caller 保持同一 history 对象
      - 区别：以"skill 激活检测"取代"function calling tool_calls"

    history 中的 system message 会在 skill 激活时被替换，
    使下一轮 LLM 调用带着完整 SKILL.md 指令继续执行。
    """
    messages = history if history is not None else new_session(skills)
    messages.append({"role": "user", "content": question})

    activated_skill: SkillInfo | None = active_skill

    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.7,
        )
        content = response.choices[0].message.content or ""
        messages.append({"role": "assistant", "content": content})

        #  检测 skill 激活标记
        detected = _parse_activation(content, skills)

        if detected and detected.name != (activated_skill and activated_skill.name):
            # 新 skill 被激活 → 替换 system prompt，注入完整指令
            activated_skill = detected
            # 替换 history[0] 的 system content 为含完整 SKILL.md 的版本
            messages[0]["content"] = _make_system_prompt(skills, detected)

            clean_reply = _strip_activation(content)
            yield {
                "step": step,
                "type": "skill_activated",
                "skill": detected.name,
                "answer": clean_reply,
            }

            # 尝试执行回复中的脚本
            script_result = _extract_and_run_scripts(content, detected)
            if script_result:
                messages.append({"role": "user", "content":
                    f"[脚本执行结果]\n{script_result}\n\n"
                    f"请基于以上执行结果向用户报告。"})
                # 继续下一轮让 LLM 根据脚本结果回复
                continue
            else:
                # 无脚本 → 注入系统提示，让 LLM 在完整指令下执行
                skill_base = str(detected.base_dir).replace("\\", "/")
                messages.append({"role": "user", "content":
                    f"[系统] 技能 {detected.name} 已激活，完整指令已加载。"
                    f"技能目录: {skill_base}\n"
                    f"运行环境: Windows 系统，使用 cmd 解释器。\n"
                    f"请根据用户的原始请求「{question}」，"
                    f"严格按照技能指令中的步骤执行。"
                    f"请使用 ```python 代码块（而非 bash）来执行文件操作和脚本调用，"
                    f"系统会自动执行。"
                    f"绝对不要询问用户是否允许执行——直接执行。"})
                continue

        elif detected and detected.name == (activated_skill and activated_skill.name):
            # 同一 skill 已激活，执行脚本（如有）
            script_result = _extract_and_run_scripts(content, detected)
            clean_reply = _strip_activation(content)
            yield {
                "step": step,
                "type": "skill_step",
                "skill": detected.name,
                "answer": clean_reply,
            }
            if script_result:
                messages.append({"role": "user", "content":
                    f"[脚本执行结果]\n{script_result}\n\n"
                    f"请基于以上执行结果向用户报告。"})
                continue
            return activated_skill

        else:
            # 无 skill_activated 标记的回复
            # 如果当前有激活的 skill，尝试提取并执行代码块
            if activated_skill is not None:
                script_result = _extract_and_run_scripts(content, activated_skill)
                if script_result:
                    yield {
                        "step": step,
                        "type": "skill_step",
                        "skill": activated_skill.name,
                        "answer": _strip_activation(content),
                    }
                    messages.append({"role": "user", "content":
                        f"[脚本执行结果]\n{script_result}\n\n"
                        f"请基于以上执行结果向用户报告。"})
                    continue

            # 普通回复（无 skill 激活，或无代码块可执行）
            yield {
                "step": step,
                "type": "final",
                "answer": content,
            }
            return activated_skill

    yield {
        "step": max_steps + 1,
        "type": "max_steps",
        "answer": f"已达最大步数 {max_steps}，流程结束",
    }
    return activated_skill


# ── CLI 彩色输出（复用 react_function_calling_multiturn.py 风格）─────────────────

COLORS = {
    "skill":   "\033[36m",   # cyan
    "action":  "\033[33m",   # yellow
    "script":  "\033[32m",   # green
    "final":   "\033[35m",   # magenta
    "error":   "\033[31m",   # red
    "dim":     "\033[2m",
    "bold":    "\033[1m",
    "reset":   "\033[0m",
}

def _c(color: str, text: str) -> str:
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def _print_one_round(question: str, skills: list[SkillInfo], max_steps: int,
                     history: list, active_skill: SkillInfo | None):
    """打印一轮对话的彩色输出，返回 generator 的 return 值（激活的 skill）"""
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    skill_label = active_skill.name if active_skill else "通用模式"
    print(f"模型: {MODEL}  当前技能: {skill_label}")
    print('='*60)

    start = time.time()
    result_skill = active_skill

    # 手动迭代 generator 以捕获 return 值（for 循环会丢弃 return 值）
    gen = run(question, skills, max_steps=max_steps,
              history=history, active_skill=active_skill)
    try:
        while True:
            step_data = next(gen)
            stype = step_data["type"]

            if stype == "skill_activated":
                print(_c("skill", f"\n🎯 [Step {step_data['step']}] 技能激活: {step_data['skill']}"))
                if step_data["answer"]:
                    print(_c("final", f"   {step_data['answer']}"))

            elif stype == "skill_step":
                print(_c("action", f"\n⚙️  [Step {step_data['step']}] 技能执行: {step_data['skill']}"))
                if step_data["answer"]:
                    print(_c("final", f"   {step_data['answer']}"))

            elif stype == "final":
                elapsed = time.time() - start
                print(f"\n{'─'*60}")
                print(_c("final", f"✅ 回复:\n{step_data['answer']}"))
                print(f"\n共 {step_data['step']} 步，耗时 {elapsed:.1f}s")

            elif stype == "max_steps":
                print(_c("error", f"\n⚠️  {step_data.get('answer', '')}"))
    except StopIteration as e:
        # 捕获 generator 的 return 值（即激活的 skill）
        result_skill = e.value if e.value is not None else active_skill

    return result_skill


def run_interactive_and_print(skills_dir: Path, max_steps: int = 10):
    """
    多轮交互 CLI：与 react_function_calling_multiturn.py 的
    run_interactive_and_print() 完全同构，额外维护 active_skill 状态。

    """
    # L1：启动时扫描 skill 目录
    skills = scan_skills(skills_dir)

    print(f"\n{COLORS['bold']}Skill Agent — 渐进式技能加载演示{COLORS['reset']}")
    print(f"模型: {COLORS['skill']}{MODEL}{COLORS['reset']}")
    print(f"Skills 目录: {skills_dir}")
    print(f"发现 {len(skills)} 个技能:")
    for s in skills:
        refs = list_references(s)
        ref_label = f"  [references: {', '.join(refs)}]" if refs else ""
        print(f"  • {s.name} v{s.version}{ref_label}")
        print(f"    {COLORS['dim']}{s.description[:80]}{COLORS['reset']}")

    history = new_session(skills)
    active_skill: SkillInfo | None = None

    try:
        while True:
            try:
                user_input = input(f"\n{COLORS['bold']}你 > {COLORS['reset']}").strip()
            except EOFError:
                break

            if not user_input:
                print("\n（收到空输入，结束会话）")
                break

            # ── 执行一轮对话 ──────────────────────────────────────────────────
            result_skill = _print_one_round(
                user_input, skills, max_steps, history, active_skill
            )

            # 更新激活状态（run() 返回了激活的 skill）
            if result_skill and result_skill.name != (active_skill and active_skill.name):
                active_skill = result_skill
                print(f"\n{COLORS['dim']}[当前激活技能: {active_skill.name}，"
                      f"后续对话将沿用此技能指令]{COLORS['reset']}")

    except KeyboardInterrupt:
        print("\n\n（收到 Ctrl+C，结束会话）")


# ── 入口 ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Skill Agent — 渐进式技能加载对话 Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python skill_agent.py
  python skill_agent.py --skills_dir ../skills --max_steps 8
  python skill_agent.py --skills_dir "D:/path/to/skills"
        """,
    )
    parser.add_argument(
        "--skills_dir",
        default=str(Path(__file__).parent.parent / "skills"),
        help="skills 目录路径（默认: ../skills）",
    )
    parser.add_argument(
        "--max_steps", type=int, default=10,
        help="每轮对话最大步数（默认: 10）",
    )
    args = parser.parse_args()

    run_interactive_and_print(Path(args.skills_dir), args.max_steps)
