"""
run_agent.py — 读取skill文件，调用模型，循环执行工具直到给出最终回答
"""

import json
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

# 让 skill_tools 可被 import（直接 python 运行本脚本也能找到）
sys.path.insert(0, str(Path(__file__).parent))

from skill_tools import read_skill_frontmatter, read_skill_content, execute_skill_command  # noqa: E402

# ── LLM 配置（参考 mode_function_call/run_function_call.py）─────────────────

PROVIDERS = {
    "deepseek": {
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "dashscope": {
        "api_key": os.environ.get("DASHSCOPE_API_KEY", ""),
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
}


def build_client(provider: str):
    cfg = PROVIDERS[provider]
    if not cfg["api_key"]:
        print(f"错误：未设置 {provider.upper()}_API_KEY", file=sys.stderr)
        sys.exit(1)
    return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"]), cfg["model"]


# ── 工具 Schema：两个拆分后的工具 ───────────────────────────────────────────

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_skill_frontmatter",
            "description": "读取指定skill的frontmatter内容",
        "parameters": { # 无参数
            "type": "object",
            "properties": {},
            "required": []
            }
        },
    },

    {
        "type": "function",
        "function": {
            "name": "read_skill_content",
            "description": "读取指定skill的内容",
            "parameters": {
                "type": "object",
                "properties": {
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_skill_command",
            "description": "执行skill里指定的命令行",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "description": "要执行的skill命令行列表",
                        "items": {"type": "string"},
                    },
                },
                "required": ["command"],
            },
        },
    }
]

# 工具名 → 后端函数 的派发表（业务逻辑与协议层分离）
TOOL_DISPATCH = {
    "read_skill_frontmatter": read_skill_frontmatter,
    "read_skill_content": read_skill_content,
    "execute_skill_command": execute_skill_command,
}

SYSTEM_PROMPT = (
    "你是一名skill助手，有三个独立工具可用：read_skill_frontmatter、read_skill_content、execute_skill_command（skill命令行）。"
    "请按需调用工具，必要时可链式调用。"
    "只依据工具返回的数据作答，不要编造。"
)

# ── 【核心】agent loop：模型循环调用工具直到给出最终回答 ────────────────────

MAX_STEPS = 10  # 防御性兜底，避免模型无限循环


def run(client, model: str, question: str, verbose: bool = True) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    t0 = time.time()
    tool_call_log = []

    for step in range(1, MAX_STEPS + 1):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        # 模型本轮不再调用工具 → 已经是最终回答，退出循环
        if not getattr(msg, "tool_calls", None):
            if verbose:
                print(f"  → [llm] 最终回答（第{step}轮，共{time.time() - t0:.1f}s）")
            return {
                "answer": msg.content or "",
                "tool_calls": tool_call_log,
                "steps": step,
                "elapsed": time.time() - t0,
            }

        # 把 assistant 这条带 tool_calls 的消息转为 dict 回填，保留 tool_calls 元数据
        assistant_entry = {
            "role": "assistant",
            "content": getattr(msg, "content", "") or "",
            "tool_calls": [],
        }
        for tc in getattr(msg, "tool_calls", []) or []:
            assistant_entry["tool_calls"].append({
                "id": getattr(tc, "id", None),
                "type": getattr(tc, "type", "tool_call"),
                "function": {
                    "name": getattr(tc.function, "name", None) if hasattr(tc, "function") else None,
                    "arguments": getattr(tc.function, "arguments", None) if hasattr(tc, "function") else None,
                },
            })
        messages.append(assistant_entry)

        # 逐个执行模型本轮要调的工具
        for tc in msg.tool_calls:
            name = tc.function.name
            # 解析 arguments —— 支持 dict 或 JSON 字符串，容错 JSONDecodeError
            raw_args = getattr(tc.function, "arguments", None)
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args or "{}")
                except json.JSONDecodeError:
                    args = {}
            else:
                args = raw_args or {}
            tool_call_log.append({"name": name, "args": args})
            if verbose:
                print(f"  → [tool step {step}] {name}({args})")
            fn = TOOL_DISPATCH.get(name)
            if fn is None:
                result = f"未知工具：{name}"
            else:
                try:
                    result = fn(**args)
                except TypeError as e:
                    result = f"参数错误：{e}"
                except Exception as e:
                    result = f"工具执行失败：{e}"
                # 统一把工具返回转换为字符串（dict 等会被 json.dumps）以便安全切片/回填
                if isinstance(result, str):
                    result_str = result
                else:
                    try:
                        result_str = json.dumps(result, ensure_ascii=False)
                    except Exception:
                        result_str = str(result)

                preview = (result_str or "")[:120].replace("\n", " ")
                if verbose:
                    print(f"    ↩ {preview}{'...' if len(result_str) > 120 else ''}\n")
                # 以 role=tool 回填，tool_call_id 必须对上，content 保证为字符串
                messages.append({
                    "role": "tool",
                    "tool_call_id": getattr(tc, "id", None),
                    "content": result_str,
                })
        # 循环回到顶部，让模型看到工具结果后决定：继续调工具 or 给最终回答

    return {
        "answer": "（达到最大步数，模型仍未给出最终回答）",
        "tool_calls": tool_call_log,
        "steps": MAX_STEPS,
        "elapsed": time.time() - t0,
    }


# ── 入口 ───────────────────────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="作业：拆分天气工具 + agent loop")
    parser.add_argument("--question", "-q", help="单个问题")
    parser.add_argument("--demo", action="store_true", help="跑内置示例问题集")
    parser.add_argument("--provider", default="deepseek", choices=PROVIDERS.keys())
    parser.add_argument("--quiet", action="store_true", help="少输出")
    args = parser.parse_args()

    client, model = build_client(args.provider)
    print(f"[Split Weather Agent] provider={args.provider} model={model}\n")

    questions = [args.question] if args.question else [""]
    for i, q in enumerate(questions, 1):
        print("=" * 60)
        print(f"Q{i}：{q}")
        print("=" * 60)
        result = run(client, model, q, verbose=not args.quiet)
        print("\n最终回答：")
        print(result["answer"])
        print(f"\n（工具调用 {len(result['tool_calls'])} 次，循环 {result['steps']} 轮，"
              f"耗时 {result['elapsed']:.1f}s）\n")


if __name__ == "__main__":
    main()
