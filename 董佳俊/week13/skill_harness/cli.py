"""
Skill Harness CLI — 渐进式加载演示

教学重点：
  1. 每个 Phase 都有清晰的日志输出，展示"渐进式"的含义
  2. L0 扫描极快（只读 frontmatter），对比全量加载的耗时
  3. L1 匹配只靠 name + description，不读完整指令
  4. L2 只加载匹配到的 skill，未匹配的零开销
  5. L3 引用按需读取，不主动加载不需要的参考文件

使用方式：
    cd skill_harness/
    python cli.py

命令：
    直接输入文本    → 自动匹配 + 加载 + 模拟执行
    /skills         → 查看已发现的技能列表 (L0)
    /load <name>    → 手动加载指定技能 (L2)
    /ref <skill> <ref> → 按需加载参考文件 (L3)
    /stats          → 查看 harness 运行统计
    /help           → 帮助
    /exit           → 退出
"""

import os
import sys
import time
import logging
from pathlib import Path

# 确保可以从 skill_harness 目录运行
_THIS_DIR = Path(__file__).parent
if str(_THIS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR.parent))

from skill_harness.harness import SkillHarness, DEFAULT_SKILLS_DIRS
from skill_harness.models import Skill, MatchResult

# ── 终端着色 ──────────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
WHITE = "\033[37m"

# 如果输出被重定向（非终端），禁用颜色
if not sys.stdout.isatty():
    RESET = BOLD = DIM = CYAN = GREEN = YELLOW = MAGENTA = RED = WHITE = ""


def cprint(color: str, *args, **kwargs):
    """带颜色打印"""
    text = " ".join(str(a) for a in args)
    print(f"{color}{text}{RESET}", **kwargs)


def print_header(title: str):
    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}")


def print_phase(phase: str, title: str):
    print(f"\n{CYAN}── {phase}: {title} ──{RESET}")


# ── CLI 命令处理 ─────────────────────────────────────────────────────

class SkillHarnessCLI:
    """CLI 交互式演示"""

    def __init__(self):
        self.harness = SkillHarness(skills_dirs=DEFAULT_SKILLS_DIRS)
        self.running = True

    def run(self):
        """主入口"""
        self._print_banner()

        # L0: 启动扫描
        print_phase("Phase 0 (L0)", "启动扫描 — 仅读取 frontmatter")
        t0 = time.perf_counter()
        count = self.harness.startup()
        elapsed = round((time.perf_counter() - t0) * 1000, 2)

        cprint(GREEN, f"  ✓ 发现 {count} 个技能（耗时 {elapsed}ms）")
        for s in self.harness.get_skill_list():
            desc = s["description"][:70]
            ver = f" v{s['version']}" if s["version"] else ""
            print(f"    {BOLD}{s['name']}{RESET}{ver}")
            print(f"    {DIM}{desc}...{RESET}")

        cprint(DIM, f"\n  命令: /skills | /load <name> | /ref <skill> <ref> | /stats | /help | /exit")

        # 交互循环
        while self.running:
            try:
                user_input = input(f"\n{BOLD}你：{RESET}").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                self._handle_command(user_input)
            else:
                self._handle_query(user_input)

        print(f"\n{GREEN}再见！{RESET}")

    def _handle_command(self, cmd_line: str):
        """处理 / 命令"""
        parts = cmd_line.split(maxsplit=2)
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if cmd == "/exit" or cmd == "/quit":
            self.running = False

        elif cmd == "/skills" or cmd == "/list":
            self._cmd_skills()

        elif cmd == "/load":
            self._cmd_load(args)

        elif cmd == "/ref":
            self._cmd_ref(args)

        elif cmd == "/stats":
            self._cmd_stats()

        elif cmd == "/help":
            self._cmd_help()

        else:
            cprint(YELLOW, f"未知命令: {cmd}。输入 /help 查看可用命令。")

    def _handle_query(self, user_input: str):
        """处理自然语言查询 — 完整 L1→L2→L3 流水线"""
        # Phase 1: 匹配
        print_phase("Phase 1 (L1)", f"意图匹配: \"{user_input[:50]}{'...' if len(user_input) > 50 else ''}\"")
        matches = self.harness.matcher.match(user_input)

        if not matches:
            cprint(YELLOW, "  ✗ 未匹配到任何技能")
            cprint(DIM, "  提示: 尝试 /skills 查看可用技能，或输入更明确的描述。")
            return

        # 展示匹配结果
        for i, m in enumerate(matches):
            score_pct = int(m.score * 100)
            cprint(GREEN, f"  ✓ #{i+1} {BOLD}{m.skill.meta.name}{RESET} {GREEN}({m.match_type}, {score_pct}%){RESET}")
            if m.matched_keywords:
                print(f"    命中关键词: {', '.join(m.matched_keywords)}")

        # Phase 2: 渐进加载
        best = matches[0]
        if best.score >= 0.3:
            print_phase("Phase 2 (L2)", f"渐进加载: {best.skill.meta.name}")
            t_load = time.perf_counter()

            # 只加载最佳匹配的 skill
            skill = self.harness.loader.load_skill(best.skill.meta)
            load_ms = round((time.perf_counter() - t_load) * 1000, 2)

            print(f"  指令长度: {len(skill.instructions)} 字符")
            print(f"  参考文件: {len(skill.references)} 个")
            if skill.references:
                for name, content in skill.references.items():
                    status = f"{len(content)} 字符" if content else "未加载"
                    print(f"    {DIM}📄 {name} [{status}]{RESET}")
            print(f"  脚本文件: {len(skill.scripts)} 个")
            for sp in skill.scripts:
                print(f"    {DIM}⚙ {sp.name}{RESET}")
            print(f"  加载耗时: {load_ms}ms")

            # 组装上下文
            print_phase("Context", "上下文组装")
            context = self.harness.build_context([skill], user_input, matches)
            print(f"  上下文长度: {len(context)} 字符")
            print(f"  {DIM}（可直接注入 LLM System Prompt）{RESET}")

            # 尝试 LLM 执行
            print_phase("LLM", "尝试 LLM 执行...")
            try:
                from skill_harness.llm_config import is_available
                if is_available():
                    response = self.harness.run_with_llm(context)
                    print(f"{GREEN}Muse：{RESET}{response[:500]}")
                    if len(response) > 500:
                        print(f"{DIM}...（回答共 {len(response)} 字符，已截断）{RESET}")
                else:
                    cprint(DIM, "  LLM 不可用（API Key 未设置），跳过执行。")
                    cprint(DIM, "  设置方式: export DEEPSEEK_API_KEY=your-key")
            except Exception as e:
                cprint(YELLOW, f"  LLM 不可用: {e}")
                cprint(DIM, "  上下文已组装完毕，可手动查看。")
        else:
            cprint(YELLOW, f"  最佳匹配得分过低 ({best.score:.2f})，跳过加载。")

    def _cmd_skills(self):
        """列出所有已发现技能"""
        print_header("已发现技能 (L0 注册表)")
        for s in self.harness.get_skill_list():
            ver = f" v{s['version']}" if s["version"] else ""
            print(f"  {BOLD}{s['name']}{RESET}{ver}")
            print(f"  {DIM}{s['description']}{RESET}\n")

        stats = self.harness.get_stats()
        print(f"  共 {stats['discovered_skills']} 个技能 | "
              f"已加载 {stats['loaded_skills']} 个 | "
              f"参考文件已读 {stats['references_loaded']} 个")

    def _cmd_load(self, args: list[str]):
        """手动加载指定技能"""
        if not args:
            cprint(YELLOW, "用法: /load <skill_name>")
            return

        name = args[0]
        meta = self.harness.registry.get(name)
        if not meta:
            cprint(YELLOW, f"技能 '{name}' 未找到。使用 /skills 查看可用列表。")
            return

        print_phase("Phase 2 (L2)", f"手动加载: {name}")
        t0 = time.perf_counter()
        skill = self.harness.loader.load_skill(meta)
        elapsed = round((time.perf_counter() - t0) * 1000, 2)

        cprint(GREEN, f"  ✓ 已加载: {name}")
        print(f"  指令: {len(skill.instructions)} 字符")
        print(f"  参考: {len(skill.references)} 个")
        print(f"  脚本: {len(skill.scripts)} 个")
        print(f"  耗时: {elapsed}ms")

        # 展示指令前 20 行
        lines = skill.instructions.split("\n")[:20]
        preview = "\n".join(lines)
        print(f"\n  {DIM}── 指令预览 (前20行) ──{RESET}")
        print(f"  {DIM}{preview}{RESET}")

    def _cmd_ref(self, args: list[str]):
        """按需加载参考文件 (L3)"""
        if len(args) < 2:
            cprint(YELLOW, "用法: /ref <skill_name> <ref_name>")
            cprint(DIM, "示例: /ref baoyu-diagram architecture")
            return

        skill_name, ref_name = args[0], args[1]

        print_phase("Phase 3 (L3)", f"按需加载参考: {ref_name} → {skill_name}")
        t0 = time.perf_counter()
        content = self.harness.load_reference(skill_name, ref_name)
        elapsed = round((time.perf_counter() - t0) * 1000, 2)

        if content:
            cprint(GREEN, f"  ✓ 已加载: {ref_name} ({len(content)} 字符, {elapsed}ms)")
            print(f"\n  {DIM}── 内容预览 (前 500 字符) ──{RESET}")
            print(f"  {content[:500]}")
            if len(content) > 500:
                print(f"  {DIM}...（共 {len(content)} 字符）{RESET}")
        else:
            cprint(YELLOW, f"  ✗ 参考文件 '{ref_name}' 未找到")
            # 提示可用参考
            skill = self.harness.loader._cache.get(skill_name)
            if skill and skill.references:
                available = list(skill.references.keys())
                print(f"  可用参考: {', '.join(available)}")

    def _cmd_stats(self):
        """查看统计"""
        print_header("Harness 运行统计")
        stats = self.harness.get_stats()
        for key, value in stats.items():
            print(f"  {BOLD}{key}{RESET}: {value}")

    def _cmd_help(self):
        """帮助"""
        print_header("命令帮助")
        print(f"  {BOLD}直接输入文本{RESET}    自动匹配 skill → 加载 → 执行")
        print(f"  {BOLD}/skills{RESET}        查看已发现的技能列表 (L0)")
        print(f"  {BOLD}/load <name>{RESET}   手动加载指定技能 (L2)")
        print(f"  {BOLD}/ref <skill> <ref>{RESET}  按需加载参考文件 (L3)")
        print(f"  {BOLD}/stats{RESET}        查看运行统计")
        print(f"  {BOLD}/help{RESET}         显示此帮助")
        print(f"  {BOLD}/exit{RESET}         退出")

    @staticmethod
    def _print_banner():
        print(f"{BOLD}{CYAN}")
        print(f"╔{'═' * 58}╗")
        print(f"║{' ' * 10}渐进式 Skill Harness — CLI 演示{' ' * 15}║")
        print(f"╚{'═' * 58}╝")
        print(f"{RESET}")
        print(f"  本工具演示渐进式加载 Skills 的完整流程：")
        print(f"  {CYAN}L0{RESET} 注册表扫描 → {CYAN}L1{RESET} 意图匹配 → {CYAN}L2{RESET} 渐进加载 → {CYAN}L3{RESET} 按需引用")
        print(f"  {DIM}未匹配的 skill 零 I/O 开销，参考文件仅在明确引用时读取{RESET}")


# ── 入口 ──────────────────────────────────────────────────────────────

def main():
    """CLI 入口"""
    # 配置日志（仅显示警告和错误，避免干扰 CLI 输出）
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    cli = SkillHarnessCLI()
    cli.run()


if __name__ == "__main__":
    main()
