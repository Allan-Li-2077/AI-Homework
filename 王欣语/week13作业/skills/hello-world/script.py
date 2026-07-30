#!/usr/bin/env python3
"""
Hello World Skill 脚本

接收用户输入，返回友好的问候语和当前时间。
"""

import sys
from datetime import datetime


def main():
    # 获取用户输入（Harness 传递的参数）
    user_input = sys.argv[1] if len(sys.argv) > 1 else "你好"

    # 获取当前时间
    now = datetime.now()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    hour = now.hour

    # 根据时间选择问候语
    if 5 <= hour < 12:
        greeting = "早上好"
    elif 12 <= hour < 18:
        greeting = "下午好"
    elif 18 <= hour < 22:
        greeting = "晚上好"
    else:
        greeting = "夜深了"

    # 输出结果
    print(f"👋 {greeting}！我是 Hello World Skill。")
    print(f"🕐 当前时间: {time_str}")
    print(f"💬 你说了: {user_input}")
    print()
    print("✨ 这是 Harness 渐进式加载执行的第一个 Skill！")


if __name__ == "__main__":
    main()
