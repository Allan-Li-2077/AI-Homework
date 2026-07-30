"""
Skill Harness — 渐进式加载执行框架（CLI 演示）

教学重点：
  1. 触发层（Always-loaded）：只加载 skill 的 name + description
  2. 按需层（On Demand）：用户输入匹配 trigger 后，注入完整 SKILL.md
  3. 执行层（In Context）：LLM 根据 skill 指令完成任务

命令：
  /skills       列出所有已注册 skill（触发层信息）
  /match <文本>  测试某段文本会匹配到哪个 skill
  /reload       重新扫描 skills 目录
  /exit         退出

使用方式：
  python src/harness.py [--skills-dir <path>]
"""

import os
import sys
import argparse
from pathlib import Path

# Windows OpenMP 冲突修复
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# 让 src/ 内的模块可以相互 import
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm_config import get_chat_client, current_model_info
from src.skill_registry import scan_skills, SkillIndex
from src.trigger_matcher import match_skill, keyword_filter

# ── 终端颜色 ────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
DIM = "\033[2m"
RED = "\033[31m"


def print_banner(skills: list[SkillIndex], model_info: dict):
    """打印启动横幅 + 触发层索引"""
    print(f"\n{BOLD}{'═'*60}{RESET}")
    print(f"{BOLD}  Skill Harness — 渐进式加载演示{RESET}")
    print(f"  模型：{CYAN}{model_info['display']}{RESET}")
    print(f"{BOLD}{'═'*60}{RESET}")

    print(f"\n{CYAN}  触发层索引（Always-loaded，<50 tokens/skill）{RESET}")
    print(f"{CYAN}{'─'*60}{RESET}")
    for s in skills:
        desc_preview = s.description[:80] + ("..." if len(s.description) > 80 else "")
        print(f"  {GREEN}{s.name}{RESET}  {DIM}[~{len(s.description)} 字符]{RESET}")
        print(f"    {DIM}{desc_preview}{RESET}")
    print(f"{CYAN}{'─'*60}{RESET}")
    print(f"  输入内容自动匹配 skill，/skills 查看列表，/exit 退出\n")


def print_skill_loaded(skill: SkillIndex):
    """打印按需加载信息"""
    content = skill.load_full()
    print(f"\n{MAGENTA}  ┌──────────────────────────────────────────────┐{RESET}")
    print(f"{MAGENTA}  │ 按需加载：{skill.name:<34}│{RESET}")
    print(f"{MAGENTA}  │ 完整 SKILL.md：{len(content)} 字符 (~{skill.full_token_estimate} tokens) │{RESET}")
    print(f"{MAGENTA}  └──────────────────────────────────────────────┘{RESET}")


def print_skill_unloaded(skill: SkillIndex):
    """打印上下文释放信息"""
    print(f"{DIM}  [上下文释放] {skill.name} 已从上下文移除{RESET}\n")


def print_layer_status(skills: list[SkillIndex], active_skill: SkillIndex | None):
    """打印当前三层加载状态"""
    print(f"\n{DIM}  ── 三层加载状态 ──{RESET}")
    for s in skills:
        if s.is_loaded:
            print(f"    {GREEN}●{RESET} {s.name} {DIM}(已加载 {s.full_token_estimate} tokens){RESET}")
        else:
            print(f"    {DIM}○ {s.name} (仅触发层){RESET}")
    if active_skill:
        print(f"    {CYAN}▶ 活跃 Skill：{active_skill.name}{RESET}")
    print()


def do_reload(skills_dir: Path) -> list[SkillIndex]:
    """重新扫描 skills 目录"""
    skills = scan_skills(skills_dir)
    print(f"{GREEN}  已重新扫描，找到 {len(skills)} 个 Skill。{RESET}")
    for s in skills:
        print(f"    - {s.name}")
    return skills


def build_system_prompt(active_skill: SkillIndex | None, base_prompt: str) -> str:
    """组装 system prompt，注入活跃 skill 的完整内容"""
    parts = [base_prompt]
    if active_skill and active_skill.is_loaded:
        parts.append(f"\n\n## 当前激活的 Skill\n\n{active_skill.load_full()}")
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Skill Harness — 渐进式加载演示")
    default_skills_dir = Path(__file__).parent.parent.parent / "skills"
    parser.add_argument("--skills-dir", type=Path, default=default_skills_dir)
    args = parser.parse_args()

    skills_dir = args.skills_dir.resolve()
    if not skills_dir.is_dir():
        print(f"{RED}错误：skills 目录不存在：{skills_dir}{RESET}")
        sys.exit(1)

    # 初始化
    try:
        model_info = current_model_info()
    except EnvironmentError as e:
        print(f"{YELLOW}{e}{RESET}")
        sys.exit(1)

    client, model = get_chat_client()
    skills = scan_skills(skills_dir)
    print_banner(skills, model_info)

    messages: list[dict] = []
    active_skill: SkillIndex | None = None

    BASE_SYSTEM_PROMPT = (
        "你是一个智能助手。如果 system prompt 中包含 Skill 指令，"
        "请严格按照 Skill 的要求执行任务。"
    )

    while True:
        try:
            user_input = input(f"{BOLD}你：{RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            user_input = "/exit"

        if not user_input:
            continue

        # ── 命令处理 ──────────────────────────────────────────────
        if user_input == "/exit":
            if active_skill:
                active_skill.unload()
                print_skill_unloaded(active_skill)
            print("再见！")
            break

        if user_input == "/skills":
            print(f"\n{CYAN}已注册 Skills（触发层）：{RESET}")
            for s in skills:
                status = f"{GREEN}[已加载]{RESET}" if s.is_loaded else f"{DIM}[仅索引]{RESET}"
                print(f"  {status} {s.name}  {DIM}{s.trigger_hint[:60]}...{RESET}")
            print()
            continue

        if user_input.startswith("/match"):
            test_text = user_input[6:].strip()
            if not test_text:
                print(f"{YELLOW}用法：/match <测试文本>{RESET}")
                continue
            candidates = keyword_filter(test_text, skills)
            if candidates:
                print(f"  关键词命中：{', '.join(s.name for s in candidates)}")
                best = match_skill(client, model, test_text, skills)
                if best:
                    print(f"  {GREEN}最佳匹配：{best.name}{RESET}")
                else:
                    print(f"  {DIM}LLM 判定：无匹配{RESET}")
            else:
                print(f"  {DIM}关键词未命中任何 Skill{RESET}")
            print()
            continue

        if user_input == "/reload":
            skills = do_reload(skills_dir)
            continue

        if user_input == "/layers":
            print_layer_status(skills, active_skill)
            continue

        # ── 渐进式 Skill 匹配 ────────────────────────────────────
        matched = match_skill(client, model, user_input, skills)

        # 如果匹配到新 skill，释放旧的
        if matched and active_skill and matched.name != active_skill.name:
            active_skill.unload()
            print_skill_unloaded(active_skill)

        if matched:
            # 按需加载
            if not matched.is_loaded:
                print_skill_loaded(matched)
            active_skill = matched
        else:
            # 无匹配，释放当前 skill
            if active_skill:
                active_skill.unload()
                print_skill_unloaded(active_skill)
                active_skill = None

        # ── 组装 Context Window ──────────────────────────────────
        system_prompt = build_system_prompt(active_skill, BASE_SYSTEM_PROMPT)
        api_messages = [{"role": "system", "content": system_prompt}] + messages
        api_messages.append({"role": "user", "content": user_input})

        # ── LLM 调用（流式输出）──────────────────────────────────
        tag = f"{CYAN}[skill: {active_skill.name}]{RESET} " if active_skill else ""
        print(f"{GREEN}{tag}助手：{RESET}", end="", flush=True)

        stream = client.chat.completions.create(
            model=model, messages=api_messages, temperature=0.7, stream=True
        )
        response_text = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            print(delta, end="", flush=True)
            response_text += delta
        print("\n")

        # 记录对话
        messages.append({"role": "user", "content": user_input})
        messages.append({"role": "assistant", "content": response_text})


if __name__ == "__main__":
    main()
