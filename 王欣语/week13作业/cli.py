#!/usr/bin/env python3
"""
Harness CLI - 命令行交互界面

命令：
  <任意输入>     触发 Skill 匹配与执行
  /list          列出所有已加载的 Skill
  /info <name>   查看指定 Skill 的详细信息
  /reload        重新扫描并加载所有 Skill
  /help          显示帮助信息
  /quit          退出程序

使用方式：
  python cli.py
  python cli.py --skill-dir ./my-skills
"""

import sys
import argparse
import logging
from pathlib import Path

from config import HarnessConfig
from harness import Harness


def setup_logging(level: str = "INFO"):
    """配置日志输出"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def print_banner():
    """打印欢迎信息"""
    print()
    print("╔══════════════════════════════════════════╗")
    print("║      🛠️  Skill Harness CLI               ║")
    print("║      渐进式 Skill 加载执行框架            ║")
    print("╚══════════════════════════════════════════╝")
    print()
    print("输入任意内容触发 Skill 匹配，或输入 /help 查看命令")
    print()


def print_help():
    """打印帮助信息"""
    print()
    print("📖 可用命令：")
    print("  ─────────────────────────────────────")
    print("  <任意输入>     触发 Skill 匹配与执行")
    print("  /list          列出所有已加载的 Skill")
    print("  /info <name>   查看指定 Skill 的详细信息")
    print("  /reload        重新扫描并加载所有 Skill")
    print("  /help          显示此帮助信息")
    print("  /quit          退出程序")
    print()
    print("💡 提示：")
    print("  - Skill 通过 YAML frontmatter 中的 triggers 字段匹配")
    print("  - 支持精确匹配、模糊匹配和描述匹配三种方式")
    print("  - 使用 /reload 可以在不重启的情况下加载新 Skill")
    print()


def print_skills(harness: Harness):
    """打印 Skill 列表"""
    skills = harness.list_skills()
    if not skills:
        print("⚠️  未发现任何 Skill")
        return

    print()
    print(f"📦 已加载 {len(skills)} 个 Skill：")
    print("  ─────────────────────────────────────")
    for i, skill in enumerate(skills, 1):
        triggers = ", ".join(skill.triggers) if skill.triggers else "无"
        print(f"  {i}. {skill.name} (v{skill.version})")
        print(f"     描述: {skill.description[:60]}{'...' if len(skill.description) > 60 else ''}")
        print(f"     触发词: {triggers}")
        print()


def print_skill_info(harness: Harness, name: str):
    """打印 Skill 详细信息"""
    info = harness.get_skill_info(name)
    if not info:
        print(f"❌ 未找到 Skill: {name}")
        return

    print()
    print(f"📋 Skill: {info['name']}")
    print("  ─────────────────────────────────────")
    print(f"  版本:     {info['version']}")
    print(f"  描述:     {info['description']}")
    print(f"  触发词:   {', '.join(info['triggers']) if info['triggers'] else '无'}")
    print(f"  脚本:     {info['script']}")
    print(f"  脚本类型: {info['script_type']}")
    print(f"  工作目录: {info['working_dir']}")
    print(f"  完整加载: {'是' if info['loaded'] else '否（渐进式）'}")
    print()


def handle_user_input(harness: Harness, user_input: str):
    """处理用户输入"""
    result = harness.process(user_input)

    if result is None:
        print("🤷 未找到匹配的 Skill，尝试输入 /list 查看可用 Skill")
        return

    if result.success:
        if result.stdout:
            print(result.stdout)
    else:
        print(f"❌ 执行失败: {result.error_message}")
        if result.stderr:
            print(f"   错误输出: {result.stderr}")


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description="Skill Harness CLI")
    parser.add_argument(
        "--skill-dir",
        type=str,
        default="skills",
        help="Skill 目录路径（默认: skills）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.3,
        help="匹配阈值（0~1，默认: 0.3）",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别（默认: INFO）",
    )
    args = parser.parse_args()

    # 设置日志
    setup_logging(args.log_level)

    # 创建配置
    config = HarnessConfig(
        skill_dirs=[Path(args.skill_dir)],
        match_threshold=args.threshold,
        log_level=args.log_level,
    )

    # 初始化 Harness
    harness = Harness(config).init()

    # 打印欢迎信息
    print_banner()

    # 交互循环
    while True:
        try:
            user_input = input("🎯 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not user_input:
            continue

        # 命令处理
        if user_input == "/quit":
            print("👋 再见！")
            break
        elif user_input == "/help":
            print_help()
        elif user_input == "/list":
            print_skills(harness)
        elif user_input.startswith("/info "):
            name = user_input[6:].strip()
            print_skill_info(harness, name)
        elif user_input == "/reload":
            print("🔄 重新加载 Skill...")
            harness.reload()
            print("✅ 重新加载完成")
        elif user_input.startswith("/"):
            print(f"❓ 未知命令: {user_input}，输入 /help 查看帮助")
        else:
            # 普通输入：触发 Skill 匹配
            handle_user_input(harness, user_input)


if __name__ == "__main__":
    main()
