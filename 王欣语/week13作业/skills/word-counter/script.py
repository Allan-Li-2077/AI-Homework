#!/usr/bin/env python3
"""
Word Counter Skill 脚本

统计用户输入文本的字符数、单词数和行数。
"""

import sys
import re


def count_text(text: str) -> dict:
    """
    统计文本信息

    Args:
        text: 输入文本

    Returns:
        统计结果字典
    """
    # 字符数（含空格）
    total_chars = len(text)

    # 字符数（不含空格）
    chars_no_space = len(text.replace(" ", "").replace("\n", ""))

    # 单词数（按空白分割）
    words = text.split()
    word_count = len(words)

    # 中文字符数
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))

    # 行数
    lines = text.split("\n")
    line_count = len(lines)

    # 非空行数
    non_empty_lines = len([l for l in lines if l.strip()])

    return {
        "total_chars": total_chars,
        "chars_no_space": chars_no_space,
        "word_count": word_count,
        "chinese_chars": chinese_chars,
        "line_count": line_count,
        "non_empty_lines": non_empty_lines,
    }


def main():
    # 获取用户输入
    user_input = sys.argv[1] if len(sys.argv) > 1 else ""

    if not user_input or user_input.strip() in ("统计字数", "字数统计", "计数", "count", "多少字"):
        print("📝 请输入要统计的文本内容（例如：统计字数 这是一段测试文本）")
        return

    # 统计
    stats = count_text(user_input)

    # 输出结果
    print("📊 文本统计结果")
    print("  ─────────────────────────────")
    print(f"  总字符数:     {stats['total_chars']}")
    print(f"  非空字符数:   {stats['chars_no_space']}")
    print(f"  中文字符:     {stats['chinese_chars']}")
    print(f"  单词数:       {stats['word_count']}")
    print(f"  总行数:       {stats['line_count']}")
    print(f"  非空行数:     {stats['non_empty_lines']}")
    print("  ─────────────────────────────")
    print(f"💡 文本内容: {user_input[:50]}{'...' if len(user_input) > 50 else ''}")


if __name__ == "__main__":
    main()
