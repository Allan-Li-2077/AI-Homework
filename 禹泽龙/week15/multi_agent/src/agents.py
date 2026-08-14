"""
主 agent + subagent 派发系统 - 纯同步版（线程内直接调用，无 async 嵌套）
"""
import time
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from .react_loop import ReActLoop
from .web_search import duckduckgo_search, format_search_results
from .llm_client import llm_chat_sync

logger = logging.getLogger(__name__)

# ── 系统提示 ──────────────────────────────────────────────────────────────

MAIN_SYSTEM = """你是一个智能助手，擅长判断用户问题并决定是否需要派发子agent并行处理。

**你有以下工具可用**:
{tools_desc}

**决策规则**:
- 简单事实查询（天气、汇率、单个地点信息等）→ 直接回答
- 复杂多维度问题（旅行规划、多方面调研、比较分析等）→ 必须使用 dispatch_subagents 派发多个子agent

**派发格式**:
dispatch_subagents: 子任务1 | 子任务2 | 子任务3（用 | 分隔，管道符前后有空格）

**示例**:
用户: "我想去北京玩，帮我安排行程"
你: dispatch_subagents: 北京近期天气查询 | 北京热门景点推荐 | 北京交通指南

用户: "今天北京天气怎么样"
你: 直接回答: 北京今天晴朗，温度15-25度，适宜出行
"""

MAIN_SYNTHESIS_SYSTEM = """你是一个智能助手，负责综合多个子调研员的结果，形成完整报告。
仔细阅读每个子调研员的结果，综合各维度信息，形成结构清晰、内容完整的报告。
报告要分维度组织，末尾给结论。

**输出格式**:
Thought: 我已收集所有子调研结果，现在综合成完整报告
Final Answer: [综合报告内容]
"""

SUBAGENT_SYSTEM = """你是一个专门负责单一调研任务的子agent，使用 ReAct 模式工作。

**你有以下工具可用**:
{tools_desc}

**输出格式**:
Thought: 你思考要做什么，为什么
Action: web_search
Action Input: 搜索query
Observation: 搜索结果...

Thought: 基于搜索结果继续思考
Action: final_answer
Action Input: 综合结论
"""


# ── 工具 ───────────────────────────────────────────────────────────────────

def web_search(query: str, shared_state: dict = None) -> str:
    result = duckduckgo_search(query, max_results=5)
    return format_search_results(result)


# ── 主入口（同步函数，供线程调用）─────────────────────────────────────────

def run_research(
    question: str,
    on_main_step: Optional[Callable] = None,
    on_dispatch: Optional[Callable] = None,
    on_subagent_start: Optional[Callable] = None,
    on_subagent_step: Optional[Callable] = None,
    on_subagent_done: Optional[Callable] = None,
    on_dispatch_result: Optional[Callable] = None,
    on_synthesis_start: Optional[Callable] = None,
    on_main_done: Optional[Callable] = None,
    on_final_answer: Optional[Callable] = None,
):
    """
    执行一次完整调研（同步版本）。
    所有事件通过回调函数实时推送到前端（SSE）。
    """
    shared_state = {}

    # ── Step 1: 主agent ReAct 循环 ───────────────────────────────────────
    def dispatch_tool(action_input: str, **kwargs) -> str:
        actual_shared = kwargs.get("shared_state", shared_state)
        return _dispatch_subagents(
            action_input,
            shared_state=actual_shared,
            on_dispatch=on_dispatch,
            on_subagent_start=on_subagent_start,
            on_subagent_step=on_subagent_step,
            on_subagent_done=on_subagent_done,
            on_dispatch_result=on_dispatch_result,
        )

    def main_on_step(step: dict):
        if on_main_step:
            on_main_step(step)

    main_tools = {
        "web_search": (web_search, "联网搜索，参数是查询词"),
        "dispatch_subagents": (dispatch_tool, "派发多个子agent并行调研，参数=用 | 分隔的多个子课题"),
    }
    tools_desc_main = "\n".join(f"- {n}: {d}" for n, (_, d) in main_tools.items())
    main_loop = ReActLoop(
        agent_name="main",
        tools=main_tools,
        max_steps=8,
        temperature=0.0,
        system_prompt=MAIN_SYSTEM.format(tools_desc=tools_desc_main),
    )

    main_result = main_loop.run(question, on_step=main_on_step, shared_state=shared_state)
    final_answer = main_result.final_answer

    # ── Step 2: 派发了子agent → 主agent综合 ────────────────────────────────
    dispatches = shared_state.get("dispatches", [])
    if dispatches and not final_answer.startswith("直接回答"):
        if on_synthesis_start:
            on_synthesis_start()

        sub_results = _build_subagent_summary(shared_state)
        synthesis_prompt = (
            f"基于以下子调研结果，综合成完整报告。\n\n"
            f"用户问题: {question}\n\n{sub_results}\n\n"
            f"请综合以上信息，形成结构清晰、内容完整的报告。"
        )

        # 同步 LLM 调用（无 async 嵌套）
        synthesis_response = llm_chat_sync(
            system=MAIN_SYNTHESIS_SYSTEM,
            user=f"用户问题: {question}\n\n{sub_results}\n\n请综合成报告。",
            temperature=0.0,
            max_tokens=1024,
        )

        thought_m = _re_search(r"Thought:\s*(.*?)(?=\nFinal Answer:|$)", synthesis_response, re.DOTALL)
        fa_m = _re_search(r"Final Answer:\s*(.*)", synthesis_response, re.DOTALL)
        thought = thought_m.group(1).strip() if thought_m else ""
        if fa_m:
            final_answer = fa_m.group(1).strip()
        else:
            final_answer = synthesis_response.strip()

    if on_main_done:
        on_main_done()

    if on_final_answer:
        on_final_answer(final_answer)

    return {
        "final_answer": final_answer,
        "dispatches": dispatches,
    }


# ── 派发子agent（ThreadPoolExecutor 并行）─────────────────────────────────

def _dispatch_subagents(
    task_string: str,
    shared_state: dict,
    on_dispatch: Optional[Callable] = None,
    on_subagent_start: Optional[Callable] = None,
    on_subagent_step: Optional[Callable] = None,
    on_subagent_done: Optional[Callable] = None,
    on_dispatch_result: Optional[Callable] = None,
) -> str:
    """派发多个子agent并行执行，通过回调实时推送每步。"""
    tasks = [t.strip() for t in task_string.split("|") if t.strip()]
    if not tasks:
        return "没有需要执行的任务"

    # 生成真实 subagent id 和 loop 实例
    sub_tools = {"web_search": (web_search, "联网搜索")}
    tools_desc_sub = "\n".join(f"- {n}: {d}" for n, (_, d) in sub_tools.items())
    subagents = []
    for topic in tasks:
        sid = f"sub_{uuid.uuid4().hex[:6]}"
        loop = ReActLoop(
            agent_name=sid,
            tools=sub_tools,
            max_steps=6,
            temperature=0.0,
            system_prompt=SUBAGENT_SYSTEM.format(tools_desc=tools_desc_sub),
        )
        subagents.append((sid, loop, topic))

    # 推送派发事件（拓扑图加节点）
    if on_dispatch:
        on_dispatch(
            subtopics=tasks,
            subagent_ids=[sid for sid, _, _ in subagents],
        )

    t0 = time.time()
    results = {}

    def run_one(sid: str, loop: ReActLoop, topic: str):
        """单个子agent的执行包装"""
        def step_callback(step: dict):
            if on_subagent_step:
                on_subagent_step(sid, step)

        if on_subagent_start:
            on_subagent_start(sid, topic)

        try:
            loop_result = loop.run(topic, on_step=step_callback)
            steps_dicts = [
                {
                    "step_num": s.step_num,
                    "thought": s.thought,
                    "action": s.action,
                    "action_input": s.action_input,
                    "observation": s.observation,
                    "final": (s.action == "final_answer"),
                }
                for s in loop_result.steps
            ]
            return (
                sid, topic,
                {
                    "final_answer": loop_result.final_answer,
                    "steps": steps_dicts,
                    "duration": loop_result.wall_clock,
                },
                None,
            )
        except Exception as e:
            logger.exception(f"Subagent {sid} error")
            return (
                sid, topic,
                {
                    "final_answer": f"执行出错: {type(e).__name__}: {str(e)}",
                    "steps": [],
                    "duration": 0.0,
                },
                str(e),
            )

    # ThreadPoolExecutor 并行（关键：真正的并行 wall_clock ≈ max）
    with ThreadPoolExecutor(max_workers=len(subagents)) as pool:
        futures = {
            pool.submit(run_one, sid, loop, topic): sid
            for sid, loop, topic in subagents
        }
        for future in as_completed(futures):
            sid, topic, result, error = future.result()
            results[sid] = {
                "topic": topic,
                "final_answer": result["final_answer"],
                "steps": result["steps"],
                "duration": result.get("duration", 0.0),
            }
            shared_state.setdefault("subagents", {})[sid] = results[sid]
            if on_subagent_done:
                on_subagent_done(
                    sid, results[sid]["duration"], topic, error,
                    steps=results[sid]["steps"],
                    final_answer=results[sid]["final_answer"],
                )

    wall_clock = time.time() - t0
    serial_sum = sum(r["duration"] for r in results.values())
    speedup = round(serial_sum / wall_clock, 2) if wall_clock > 0 else 1.0
    shared_state.setdefault("parallel_stats", []).append({
        "wall_clock": wall_clock,
        "serial_sum": serial_sum,
        "speedup": speedup,
    })

    if on_dispatch_result:
        on_dispatch_result(wall_clock, serial_sum, speedup, len(tasks))

    # 汇总文本（主agent的 Observation）
    parts = [
        f"【{r['topic']}】(用时{r['duration']:.1f}s)\n{r['final_answer'][:600]}"
        for r in results.values()
    ]
    return (
        f"并行调研完成：{len(tasks)}个子任务，wall-clock {wall_clock:.1f}s "
        f"(串行需 {serial_sum:.1f}s，加速 {speedup}×)\n\n"
        + "\n\n".join(parts)
    )


# ── 辅助 ──────────────────────────────────────────────────────────────────

import re

def _re_search(pattern: str, text: str, flags: int = 0):
    return re.search(pattern, text, flags)

def _build_subagent_summary(shared_state: dict) -> str:
    """把各subagent结果格式化成文本供主agent综合。"""
    parts = []
    for sid, info in shared_state.get("subagents", {}).items():
        lines = []
        for step in info.get("steps", []):
            if step.get("final") or step.get("action") == "final_answer":
                lines.append(f"[最终答案]\n{step.get('action_input', '')}")
            else:
                obs = step.get("observation") or ""
                lines.append(
                    f"Thought: {step.get('thought','')}\n"
                    f"Action: {step.get('action','')}\n"
                    f"Action Input: {step.get('action_input','')}\n"
                    f"Observation: {obs[:300]}"
                )
        parts.append(f"=== 子调研员: {info['topic']} ===\n" + "\n".join(lines))
    return "\n\n".join(parts)
