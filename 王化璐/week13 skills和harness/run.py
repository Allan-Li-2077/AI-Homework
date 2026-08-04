#!/usr/bin/env python3
"""
渐进式加载执行Skills的Harness - CLI入口

用法:
    python run.py                    # 启动交互模式
    python run.py --skills ./skills  # 指定skills目录
    python run.py -q "给我做张flash卡"  # 单次执行模式
    python run.py --verbose          # 显示详细日志

教学演示:
    这是Harness的主入口，演示了渐进式加载执行Skills的完整流程：
    1. 启动时扫描skills目录，注册所有skill元数据（轻量级）
    2. 用户输入后，匹配最合适的skill
    3. 匹配成功后，按需加载skill完整内容
    4. 按流程逐步执行skill
    5. 每步产生进度事件
"""

import sys
import os

# 确保可以导入harness模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness.harness import run_cli

if __name__ == "__main__":
    run_cli()
