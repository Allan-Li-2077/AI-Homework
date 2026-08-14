"""
主 Agent + 并行 Subagent 编排

  1. 主 agent 自己是 ReAct 循环，有 2 个工具：
     - web_search：单次联网搜索（简单问题直接用）
     - dispatch_subagents：派发多个 subagent 并行调研（多侧面研究问题用）
     主 agent 根据 query 自行决定用哪个——不是固定拓扑，是 LLM 自主路由
  2. 并行优势凸显：dispatch_subagents 一次派发 N 个 subagent，
     ThreadPoolExecutor 并行跑，wall-clock ≈ max(单agent时长)，
     而非 sum——这就是 subagent 并行的核心价值
  3. 每个 subagent 也是 ReAct 循环（只 web_search 工具），
     trace 全程捕获存入 shared_state

架构对应 PPT 的 Orchestrator-Workers 拓扑（动态：主 agent 决定派几个）。
"""

import os
import time
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from react_loop import ReActLoop
from tavily_search import tavily_search, format_search_result

logger = logging.getLogger(__name__)

# 主 agent 的系统提示——引导它自主决定派发 subagent
MAIN_SYSTEM = """你是市场调研主分析师。你有 2 个工具：
- web_search：联网搜索一次（参数=查询词）。仅用于单一事实可一次答出的问题
- dispatch_subagents：派发多个子调研员并行调研（参数=用 | 分隔的多个子课题）

【关键决策原则】
- 只要问题涉及 2 个及以上侧面（如「市场调研」「竞品分析」「行业分析」「XX 概况/现状/趋势」等），
  必须用 dispatch_subagents 把各侧面拆给子调研员并行处理，不要自己串行 web_search 多次。
  示例："新能源汽车市场调研：销量、竞争、政策" → Action: dispatch_subagents
        Action Input: 2024年中国新能源汽车销量规模 | 主要厂商竞争格局 | 政策与补贴趋势
- 只有单一事实问题（如"2024年比亚迪销量"）才直接 web_search
- 拿到子调研结果后，综合成结构化报告

报告要求：分维度组织，每个要点带来源，末尾给结论与不确定性说明。

【示例】
Question: 2023中国咖啡市场调研：市场规模、主要品牌、消费趋势
Thought: 这是多维度市场调研（3个侧面），必须派发子调研员并行收集，不能自己串行搜索
Action: dispatch_subagents
Action Input: 2023年中国咖啡市场规模与增长 | 中国咖啡主要品牌竞争格局 | 中国咖啡消费趋势与人群
Observation: 并行调研完成：3 个子调研员...（各子课题结果）
Thought: 已收齐三个维度的并行调研结果，综合成报告
Final Answer: （分维度报告）"""


def _dispatch_subagents(action_input: str, shared_state: dict = None,
                        on_subagent_step: Callable = None,
                        on_subagent_done: Callable = None,
                        on_dispatch: Callable = None,
                        serial: bool = False) -> str:
    """
    dispatch_subagents 工具实现
    
    Args:
        action_input: "子课题1 | 子课题2 | ..."（管道分隔）
        shared_state: 共享状态
        on_subagent_step: subagent 每步回调
        on_subagent_done: subagent 完成回调
        on_dispatch: 派发事件回调
        serial: True 时串行执行（用于对比测试）
    
    Returns:
        汇总文本
    """
    subtopics = [s.strip() for s in action_input.split("|") if s.strip()][:6]
    if not subtopics:
        return "未解析出子课题"
    
    shared_state = shared_state if shared_state is not None else {}
    shared_state.setdefault("subagents", {})

    # 构造 (sid, subagent, subtopic) 三元组
    defs = []
    for topic in subtopics:
        sid = f"sub_{uuid.uuid4().hex[:6]}"
        sub = ReActLoop(
            agent_name=sid,
            tools={
                "web_search": (
                    lambda q, **_: format_search_result(tavily_search(q)),
                    "联网搜索，参数是查询词"
                )
            },
            max_steps=4,
            model_tag="deepseek-chat(子)"
        )
        defs.append((sid, sub, topic))

    # 记录派发事件
    dispatch_info = {
        "subtopics": subtopics,
        "subagent_ids": [sid for sid, _, _ in defs]
    }
    shared_state.setdefault("dispatches", []).append(dispatch_info)
    if on_dispatch:
        on_dispatch(dispatch_info)

    t0 = time.time()
    results = {}

    def _run_one(sid, sub, topic):
        """运行单个 subagent"""
        res = sub.run(
            topic,
            on_step=(lambda step, sid=sid: on_subagent_step(sid, step) if on_subagent_step else None)
        )
        return sid, res

    if serial:
        # 串行模式（对比基线）
        for sid, sub, topic in defs:
            sid, res = _run_one(sid, sub, topic)
            results[sid] = (topic, res)
            shared_state["subagents"][sid] = {
                "subtopic": topic,
                "trace": res["trace"],
                "duration": res["duration"],
                "final_answer": res["final_answer"]
            }
            if on_subagent_done:
                on_subagent_done(sid, res["duration"], topic)
    else:
        # 并行模式（核心优势）
        with ThreadPoolExecutor(max_workers=len(defs)) as pool:
            futs = {pool.submit(_run_one, sid, sub, topic): sid for sid, sub, topic in defs}
            for fut in as_completed(futs):
                sid, res = fut.result()
                topic = next(t for s, _, t in defs if s == sid)
                results[sid] = (topic, res)
                shared_state["subagents"][sid] = {
                    "subtopic": topic,
                    "trace": res["trace"],
                    "duration": res["duration"],
                    "final_answer": res["final_answer"]
                }
                if on_subagent_done:
                    on_subagent_done(sid, res["duration"], topic)

    wall = round(time.time() - t0, 2)
    serial_sum = round(sum(r["duration"] for _, r in results.values()), 2)
    shared_state.setdefault("parallel_stats", []).append({
        "n_subagents": len(defs),
        "wall_clock": wall,
        "serial_sum": serial_sum,
        "speedup": round(serial_sum / wall, 2) if wall else 0
    })

    # 汇总文本（喂回主 agent 当 Observation）
    parts = [
        f"【子课题: {topic}】(用时{r['duration']}s)\n{r['final_answer'][:500]}"
        for sid, (topic, r) in results.items()
    ]
    stats = shared_state["parallel_stats"][-1]
    
    return (
        f"并行调研完成：{len(defs)} 个子调研员，wall-clock {wall}s "
        f"(串行需 {serial_sum}s，加速 {stats['speedup']}×)\n\n" + "\n\n".join(parts)
    )


def run_research(question: str, on_main_step: Callable = None,
                 on_subagent_step: Callable = None,
                 on_subagent_done: Callable = None,
                 on_dispatch: Callable = None,
                 serial: bool = False) -> dict:
    """
    执行一次市场调研
    
    Args:
        question: 调研问题
        on_main_step: 主 agent 每步回调
        on_subagent_step: subagent 每步回调
        on_subagent_done: subagent 完成回调
        on_dispatch: 派发事件回调
        serial: True 时 subagent 串行执行
    
    Returns:
        {
            "final_answer": str,
            "main_trace": list,
            "subagents": dict,
            "parallel_stats": list,
            "dispatches": list
        }
    """
    shared_state = {"subagents": {}, "dispatches": [], "parallel_stats": []}

    def dispatch_tool(action_input, shared_state=None):
        """包装 dispatch_subagents 工具"""
        info = shared_state or {}
        return _dispatch_subagents(
            action_input,
            shared_state=info,
            on_subagent_step=on_subagent_step,
            on_subagent_done=on_subagent_done,
            on_dispatch=on_dispatch,
            serial=serial
        )

    # 创建主 agent
    main = ReActLoop(
        agent_name="main",
        tools={
            "web_search": (
                lambda q, **_: format_search_result(tavily_search(q)),
                "联网搜索一次，参数=查询词"
            ),
            "dispatch_subagents": (
                dispatch_tool,
                "派发多个子调研员并行调研，参数=用 | 分隔的多个子课题"
            ),
        },
        max_steps=8,
        model_tag="deepseek-chat(主)",
        system_prompt=MAIN_SYSTEM,
    )
    
    # 运行主 agent
    result = main.run(question, on_step=on_main_step, shared_state=shared_state)
    
    return {
        "final_answer": result["final_answer"],
        "main_trace": result["trace"],
        "subagents": shared_state["subagents"],
        "parallel_stats": shared_state["parallel_stats"],
        "dispatches": shared_state["dispatches"],
    }


if __name__ == "__main__":
    import logging as _l
    _l.basicConfig(level=_l.WARNING)
    
    # 示例：调研新能源汽车市场
    q = "2024年中国新能源汽车市场调研：销量规模、主要厂商竞争格局、政策趋势"
    r = run_research(q)
    
    print(f"\n{'='*60}")
    print(f"主 agent 动作: {[s['action'] for s in r['main_trace']]}")
    print(f"派发次数: {len(r['dispatches'])} | subagent 数: {len(r['subagents'])}")
    print(f"并行统计: {r['parallel_stats']}")
    print(f"\n报告头:\n{r['final_answer'][:300]}")
