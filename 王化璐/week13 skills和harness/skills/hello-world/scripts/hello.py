"""
Hello World 示例Skill脚本

用于验证Harness的渐进式加载执行流程。
"""

import sys
import json
from datetime import datetime


def main():
    # 获取用户输入
    user_input = sys.argv[1] if len(sys.argv) > 1 else "World"
    
    # 生成响应
    response = {
        "skill": "hello-world",
        "message": f"Hello, {user_input}!",
        "timestamp": datetime.now().isoformat(),
        "steps_completed": [
            "接收用户输入",
            "加载Skill资源",
            "生成响应消息",
            "保存执行结果",
            "展示执行完成",
        ],
        "status": "success",
    }
    
    # 输出结果
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
