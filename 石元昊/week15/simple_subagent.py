"""
最简 Subagent 并行 Agent（单文件）—— Function Calling 版本

与 market_research_subagents 参考项目的关键区别：
  ┌─────────────┬──────────────────────────┬───────────────────────────┐
  │             │ 参考项目                  │ 本实现                     │
  ├─────────────┼──────────────────────────┼───────────────────────────┤
  │ 工具调用机制 │ ReAct 文本协议            │ Function Calling           │
  │             │ (正则解析 Thought/Action) │ (结构化 JSON，无解析代码)   │
  │ 主Agent形态  │ 多轮 ReAct 循环           │ 单轮规划→并行执行→聚合      │
  │ 场景        │ 市场调研 + Tavily 联网搜索 │ 通用任务分派，零外部依赖    │
  │ 子任务格式   │ "课题1|课题2" 管道分隔    │ JSON 数组，带标题和指令     │
  └─────────────┴──────────────────────────┴───────────────────────────┘

三段式流水线：
  ① Plan   主 Agent 用 function calling 把目标拆成 2~5 个独立子任务
  ② Run    ThreadPoolExecutor 并行执行，每个子任务派一个 subagent（独立 LLM 调用）
  ③ Merge  主 Agent 收齐全部子结果，综合成最终交付物

运行：
  export DEEPSEEK_API_KEY="sk-xxx"
  python simple_subagent.py
  python simple_subagent.py "给一款校园二手交易App写产品方案：功能设计、盈利模式、推广策略"

依赖：pip install openai
"""

import os
import sys
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MODEL = "qwen3.8-max"
client = None  # 懒加载，避免 import 时就要求环境变量


def get_client() -> OpenAI:
    global client
    if client is None:
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            raise EnvironmentError("请先设置环境变量 DEEPSEEK_API_KEY")
        client = OpenAI(api_key=key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    return client


# ── ① Plan：主 Agent 的唯一工具（function calling schema）────────────────────

DISPATCH_TOOL = {
    "type": "function",
    "function": {
        "name": "dispatch_subagents",
        "description": "把总任务拆分成多个可独立并行执行的子任务，派发给子代理",
        "parameters": {
            "type": "object",
            "properties": {
                "subtasks": {
                    "type": "array",
                    "description": "2~5 个相互独立、可并行的子任务",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "子任务名称"},
                            "instruction": {"type": "string",
                                            "description": "给子代理的完整任务指令，须自包含、可独立完成"},
                        },
                        "required": ["title", "instruction"],
                    },
                },
            },
            "required": ["subtasks"],
        },
    },
}

PLANNER_SYSTEM = (
    "你是任务分派主Agent。你的唯一职责：把用户的目标拆成 2~5 个相互独立、"
    "可并行执行的子任务，并调用 dispatch_subagents 工具下发。"
    "拆分原则：子任务之间不共享中间结果，各自独立完成；覆盖目标的全部侧面。"
    "不要自己回答目标本身，只负责拆分派发。"
)


def plan(goal: str) -> list[dict]:
    """主 Agent 规划：返回子任务列表 [{title, instruction}]。"""
    resp = get_client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": PLANNER_SYSTEM},
                  {"role": "user", "content": goal}],
        tools=[DISPATCH_TOOL],
        temperature=0.0,
    )
    msg = resp.choices[0].message
    if not msg.tool_calls:
        raise RuntimeError(f"主 Agent 未发起派发，直接回复了: {msg.content[:100]}")
    args = json.loads(msg.tool_calls[0].function.arguments)
    subtasks = args["subtasks"]
    logger.info(f"主 Agent 拆出 {len(subtasks)} 个子任务: {[t['title'] for t in subtasks]}")
    return subtasks


# ── ② Run：subagent 并行执行 ────────────────────────────────────────────────

WORKER_SYSTEM = (
    "你是负责单个子任务的子代理。只专注完成指派给你的任务，"
    "输出结构清晰、可直接并入总报告的结果，250 字以内。"
)


def run_subagent(subtask: dict) -> dict:
    """一个 subagent：针对自己的子任务做一次独立 LLM 调用。"""
    t0 = time.time()
    resp = get_client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": WORKER_SYSTEM},
                  {"role": "user", "content": subtask["instruction"]}],
        temperature=0.3, max_tokens=600,
    )
    out = resp.choices[0].message.content
    elapsed = round(time.time() - t0, 2)
    logger.info(f"  subagent「{subtask['title']}」完成，用时 {elapsed}s")
    return {"title": subtask["title"], "output": out, "duration": elapsed}


def run_parallel(subtasks: list[dict]) -> list[dict]:
    """ThreadPoolExecutor 并行跑全部 subagent，保持原顺序返回结果。"""
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(subtasks)) as pool:
        results = list(pool.map(run_subagent, subtasks))
    wall = round(time.time() - t0, 2)
    serial_sum = round(sum(r["duration"] for r in results), 2)
    logger.info(f"并行执行完成: 墙钟 {wall}s / 串行总和 {serial_sum}s / "
                f"加速 {round(serial_sum / wall, 2)}×")
    return results


# ── ③ Merge：主 Agent 综合各子结果 ──────────────────────────────────────────

def merge(goal: str, results: list[dict]) -> str:
    """把各 subagent 的产出交给主 Agent 综合成最终交付物。"""
    material = "\n\n".join(
        f"### 子任务《{r['title']}》(用时 {r['duration']}s)\n{r['output']}"
        for r in results)
    resp = get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "你是主Agent。综合各子代理的产出，"
             "整合成一份结构完整、去重后的最终交付物。"},
            {"role": "user", "content": f"总目标：{goal}\n\n{material}"},
        ],
        temperature=0.3, max_tokens=1500,
    )
    return resp.choices[0].message.content


# ── 入口 ────────────────────────────────────────────────────────────────────

DEFAULT_GOAL = "为 5 人小队策划一次周末两日露营：路线规划、装备清单、预算明细、安全预案"

if __name__ == "__main__":
    goal = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOAL
    print(f"\n{'='*60}\n总目标: {goal}\n{'='*60}")

    t0 = time.time()
    results = run_parallel(plan(goal))          # ① 规划 + ② 并行执行
    final = merge(goal, results)                # ③ 聚合
    total = round(time.time() - t0, 2)

    print(f"\n{'='*60}\n最终交付物（端到端 {total}s）\n{'='*60}\n{final}")
