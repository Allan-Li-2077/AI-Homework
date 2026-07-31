"""
CLI 版 Skills Harness Agent — 渐进式加载演示

教学重点：
  1. 启动时只加载 Skill 元数据（Level 0），毫秒级完成
  2. 用户输入后，关键词快筛（Layer A）→ 命中则渐进加载对应 Skill
  3. 未命中关键词 → LLM 语义判断（Layer B）→ 命中则渐进加载
  4. 每步打印加载明细，学生直观看到"渐进式"的含义
  5. 无 Skill 匹配 → 走普通对话（不加载任何 Skill，节省 token）

使用方式：
  python src/agent.py

命令：
  /skills     查看已注册的 Skill 列表
  /loaded     查看当前已加载到缓存的 Skill
  /reload     重新扫描 Skills 目录
  /exit       退出

依赖：
  pip install openai
  export DEEPSEEK_API_KEY="sk-xxx"
"""

import os
import sys
import time
import logging
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.skill_registry import SkillRegistry
from src.skill_loader import SkillLoader
from src.intent_detector import IntentDetector
from src.skill_executor import SkillExecutor
from src.llm_config import get_chat_client, current_model_info

logging.basicConfig(level=logging.WARNING)

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
DIM = "\033[2m"
RED = "\033[31m"


def print_banner():
    print(f"""
{BOLD}╔══════════════════════════════════════════════════════════╗
║           Skills Harness — 渐进式加载演示               ║
╚══════════════════════════════════════════════════════════╝{RESET}
""")


def print_skills_table(registry: SkillRegistry):
    """打印已注册的 Skills 表格"""
    skills = registry.list_skills()
    if not skills:
        print(f"{YELLOW}  未发现任何 Skill{RESET}")
        return

    print(f"\n{CYAN}{'─'*60}{RESET}")
    print(f"{CYAN}  已注册 Skills（Level 0 元数据）{RESET}")
    print(f"{CYAN}{'─'*60}{RESET}")
    for s in skills:
        icons = []
        if s.has_scripts:
            icons.append("📜")
        if s.has_references:
            icons.append("📚")
        if s.has_data:
            icons.append("💾")
        icon_str = " ".join(icons) if icons else ""

        print(f"  📦 {BOLD}{s.name}{RESET} v{s.version}  {icon_str}")
        print(f"     {DIM}{s.description[:80]}{'...' if len(s.description) > 80 else ''}{RESET}")
        print(f"     {DIM}路径: {s.dir_path}{RESET}")
    print(f"{CYAN}{'─'*60}{RESET}\n")


def print_loading_steps(skill_name: str, match, skill):
    """打印渐进式加载的每一步"""
    print(f"\n{MAGENTA}{'═'*60}{RESET}")
    print(f"{MAGENTA}  🚀 渐进式 Skill 加载{RESET}")
    print(f"{MAGENTA}{'═'*60}{RESET}")

    print(f"  {GREEN}✓ Level 0  元数据索引{RESET}  {DIM}[启动时已完成]{RESET}")
    print(f"  {GREEN}✓ 意图匹配{RESET}  "
          f"{DIM}[{match.match_layer}] 置信度 {match.confidence:.0%}{RESET}")
    print(f"     {DIM}原因: {match.reason}{RESET}")

    print(f"  {GREEN}✓ Level 1  SKILL.md 全文{RESET}  "
          f"{DIM}[{len(skill.full_content)} 字符]{RESET}")

    print(f"  {GREEN}✓ Level 2  附属资源加载{RESET}")
    if skill.scripts:
        print(f"     📜 脚本: {', '.join(skill.scripts.keys())}")
    if skill.references:
        print(f"     📚 参考: {', '.join(skill.references.keys())}")
    if skill.data_files:
        print(f"     💾 数据: {', '.join(skill.data_files.keys())}")

    print(f"{MAGENTA}{'═'*60}{RESET}")
    print(f"  {BOLD}正在使用 Skill: {skill_name}{RESET}")
    print(f"{MAGENTA}{'═'*60}{RESET}\n")


def main():
    print_banner()

    model_info = current_model_info()
    print(f"当前模型：{CYAN}{model_info['display']}{RESET}")
    print(f"输入 /skills, /loaded, /reload, /exit\n")

    try:
        get_chat_client()
    except EnvironmentError as e:
        print(f"{YELLOW}{e}{RESET}")
        sys.exit(1)

    # ── Phase 1: Level 0 索引（启动时） ─────────────────────────────────
    t0 = time.perf_counter()
    registry = SkillRegistry()
    count = registry.discover()
    t1 = time.perf_counter()

    print(f"{GREEN}[Level 0] 扫描完成：发现 {count} 个 Skills"
          f"  {DIM}（耗时 {(t1-t0)*1000:.1f}ms）{RESET}")
    print_skills_table(registry)

    loader = SkillLoader(registry)
    detector = IntentDetector(registry)
    executor = SkillExecutor(loader)

    messages: list[dict] = []

    while True:
        try:
            user_input = input(f"{BOLD}你：{RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            user_input = "/exit"

        if not user_input:
            continue

        # ── 命令处理 ──────────────────────────────────────────────────
        if user_input == "/exit":
            print("再见！")
            break

        if user_input == "/skills":
            print_skills_table(registry)
            continue

        if user_input == "/loaded":
            loaded = loader.get_loaded_names()
            if loaded:
                print(f"\n{CYAN}已加载到缓存的 Skills：{RESET}")
                for name in loaded:
                    skill = loader.get_cached(name)
                    if skill:
                        print(f"  {skill.summary()}")
            else:
                print(f"{DIM}  暂无 Skill 被加载到缓存{RESET}")
            print()
            continue

        if user_input == "/reload":
            count = registry.discover()
            loader.clear_cache()
            print(f"{GREEN}已重新扫描：发现 {count} 个 Skills，缓存已清空。{RESET}")
            print_skills_table(registry)
            continue

        # ── Phase 2: 意图检测（Layer A 关键词 → Layer B LLM）─────────────
        t2 = time.perf_counter()
        matches = detector.detect(user_input, use_llm=True)
        t3 = time.perf_counter()

        if not matches:
            # 无 Skill 匹配 → 普通对话
            print(f"  {DIM}[意图检测] 无 Skill 匹配 ({(t3-t2)*1000:.0f}ms) → 普通对话{RESET}")
            _do_chat(user_input, messages)
            continue

        best = matches[0]

        # 置信度过低 → 提示用户确认
        if best.confidence < 0.5:
            print(f"  {YELLOW}[意图检测] 低置信度匹配: {best.skill_name} "
                  f"({best.confidence:.0%}){RESET}")
            print(f"  {DIM}原因: {best.reason}{RESET}")
            confirm = input(f"  {BOLD}是否使用 {best.skill_name}？(y/n)：{RESET}").strip().lower()
            if confirm != "y":
                print(f"  {DIM}已跳过 Skill，走普通对话。{RESET}")
                _do_chat(user_input, messages)
                continue

        # ── Phase 3: 渐进式加载 + 执行 ────────────────────────────────
        skill = loader.load_level2(best.skill_name)
        if skill:
            print_loading_steps(best.skill_name, best, skill)

            # 执行 Skill
            print(f"{GREEN}执行中...{RESET}")
            result = executor.execute_with_llm(
                best.skill_name,
                user_input,
                conversation_history=messages,
                project_dir=Path.cwd(),
            )

            if result.success:
                print(f"\n{GREEN}{BOLD}Skill 执行结果：{RESET}")
                # 流式输出效果模拟（实际上 LLM 已经返回完整结果）
                print(result.llm_response)
                messages.append({"role": "user", "content": user_input})
                messages.append({"role": "assistant", "content": result.llm_response})
            else:
                print(f"\n{RED}执行失败：{result.error}{RESET}")
        else:
            print(f"{RED}无法加载 Skill: {best.skill_name}{RESET}")
            _do_chat(user_input, messages)


def _do_chat(user_input: str, messages: list[dict]):
    """普通对话（无 Skill 参与）"""
    system_prompt = (
        "你是一个智能助手。当前没有匹配的 Skill，请用你的通用能力回答用户问题。"
        "如果用户的问题可能用到某个 Skill（比如画图、做闪卡），请提示他们更明确地描述需求。"
    )
    api_messages = [{"role": "system", "content": system_prompt}] + messages
    api_messages.append({"role": "user", "content": user_input})

    print(f"{GREEN}助手：{RESET}", end="", flush=True)
    try:
        client, model = get_chat_client()
        stream = client.chat.completions.create(
            model=model, messages=api_messages, temperature=0.7, stream=True
        )
        response_text = ""
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content or ""
            if delta:
                print(delta, end="", flush=True)
                response_text += delta
        print()
        messages.append({"role": "user", "content": user_input})
        messages.append({"role": "assistant", "content": response_text})
    except Exception as e:
        print(f"\n{RED}调用失败：{e}{RESET}")


if __name__ == "__main__":
    main()
