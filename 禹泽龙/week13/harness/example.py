"""
Harness 使用示例：启动 Agent，支持多轮对话
"""

import sys
from pathlib import Path

# 将本文件父目录（skills/）加入 sys.path，使 'harness' 成为可导入的包
sys.path.insert(0, str(Path(__file__).parent.parent))

from harness import HarnessAgent, AgentConfig, get_chat_client


def main():
    # 1. 创建 LLM 客户端
    client, model = get_chat_client()

    # 2. 初始化 Harness Agent，指定 skills 目录
    skills_root = Path(__file__).parent.parent  # 指向 skills/ 目录
    agent = HarnessAgent(
        skills_root=skills_root,
        llm_client=client,
        model_name=model,
        config=AgentConfig(
            system_prompt=(
                "你是一个 AI 助手。当用户提出问题时，如果匹配到某个 skill，"
                "你会调用对应的 function 来完成任务。先推理，再调用 tool。"
            ),
            max_turns=20,
        ),
    )

    # 3. 查看已注册的所有 skills（启动时只扫描了 name + description）
    print("=== 已注册的 Skills（启动时已扫描）===")
    for s in agent.list_all_skills():
        print(f"  - {s['name']}: {s['description']}")
    print()

    # 4. 多轮对话循环
    while True:
        try:
            user_query = input(">>> 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            break

        if not user_query:
            continue

        # 退出命令
        if user_query.lower() in ("exit", "quit", "q"):
            print("已退出。")
            break

        # Harness 根据 query 预加载相关 skills（懒加载）
        agent.prepare_skills_for_query(user_query)

        # 进入对话循环，自动处理多轮 tool call
        response = agent.chat(user_query)
        print(f"\n<<< Agent: {response}\n")


if __name__ == "__main__":
    main()
