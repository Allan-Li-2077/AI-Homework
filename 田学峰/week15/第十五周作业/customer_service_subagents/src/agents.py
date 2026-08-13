"""主客服 Agent + 并行 Subagent 编排

教学重点：
  1. 主客服 agent 是 ReAct 循环，2 个工具：
     - direct_handle：自己直接处理简单单一问题（轻量快捷）
     - dispatch_subagents：把多类问题并行派发多个专长子客服处理
     主 agent 根据客户问题自主决定用哪个——LLM 自主路由，非固定拓扑
  2. 并行优势：dispatch_subagents 一次派发 N 个子客服，ThreadPoolExecutor
     并行跑，wall-clock ≈ max(单子客服时长)，而非 sum
  3. 每个 subagent 也是 ReAct 循环（带对应专长工具集），trace 全程捕获
     存 shared_state，供可视化「点节点看 ReAct 过程」

架构对应 Orchestrator-Workers（动态：主客服决定派几个、派什么专长）。
"""

import time, uuid, logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from react_loop import ReActLoop
from customer_tools import (query_order, query_logistics, apply_refund,
                            query_faq, escalate_human, get_toolset)

logger = logging.getLogger(__name__)

MAIN_SYSTEM = """你是智能客服主调度 agent，负责接待客户并高效解决问题。你有 2 个工具：
- direct_handle：自己直接处理简单单一问题（参数=处理说明，调用后系统自动跳过执行直接进 Final Answer）。仅用于单一极简问题。
- dispatch_subagents：派发多个专长子客服并行处理（参数=用 | 分隔的多条任务派单，每条格式: 任务描述#专长类型）

【专长类型】 order=订单物流查询, after_sale=售后退款, faq=政策规则咨询, escalation=升级人工

【关键决策原则】
- 客户问题涉及 2 个及以上不同子任务（如"查订单 + 退款 + 退货政策"），
  必须用 dispatch_subagents 拆给对应专长子客服并行处理，不要自己串行处理。
  示例：客户问"查 A100002 物流、给 A100003 申请退款、退货政策是什么"
  → Action: dispatch_subagents
    Action Input: 查订单 A100002 的物流状态#order | 给订单 A100003 申请退款，原因商品质量问题#after_sale | 查询退货政策#faq
- 单一极简问题（如"退货政策是什么"）才用 direct_handle
- 收齐子客服结果后，综合成礼貌、分点的客服答复

【输出要求】
答复客户时：
- 礼貌专业，分点清晰
- 涉及具体订单/物流/退款工单的要列清关键信息
- 末尾主动询问是否还有需要帮助

【示例】
客户问题: 帮我查下订单 A100002 到哪了，顺便问下退货政策
Thought: 客户有 2 个子任务：查订单物流（order 专长）+ 退货政策咨询（faq 专长），应并行派发
Action: dispatch_subagents
Action Input: 查询订单 A100002 的物流轨迹#order | 查询退货政策#faq
Observation: 并行处理完成：2 个子客服...（各子任务结果）
Thought: 已收齐订单物流信息与退货政策，综合答复客户
Final Answer: 您好！为您查询结果如下：
1. 订单 A100002（机械键盘）状态：运输中，最新物流...
2. 退货政策：7 天无理由退货...
请问还有其他可以帮您的吗？"""

# 子客服专长 → 中文角色描述（写进 subagent prompt）
ROLE_DESC = {
    "order": "订单物流查询专员，擅长查询订单状态与物流轨迹",
    "after_sale": "售后专员，擅长处理退款、退货、换货等售后申请",
    "faq": "政策规则专员，擅长解释退货/发票/会员/保修/配送等政策",
    "escalation": "升级专员，处理需要人工接入的复杂/情绪/超权限问题",
}


def _direct_handle(action_input: str, shared_state: dict = None, **_) -> str:
    """主 agent 直接处理简单问题：直接返回让 LLM 进 Final Answer。"""
    return f"已直接处理：{action_input}"


def _dispatch_subagents(action_input: str, shared_state: dict = None,
                        on_subagent_step: Callable = None,
                        on_subagent_done: Callable = None,
                        on_dispatch: Callable = None,
                        serial: bool = False) -> str:
    """dispatch_subagents 工具实现。
    action_input: "任务1#专长1 | 任务2#专长2 | ..."（管道分隔任务，#后是专长类型）
    派发 N 个 subagent 并行（ThreadPoolExecutor），收齐返回汇总文本。
    serial=True 改串行（eval A/B 对比基线）。
    并行优势量化：wall_clock vs serial_sum。
    """
    # 解析任务派单
    tasks = []
    for raw in action_input.split("|"):
        raw = raw.strip()
        if not raw:
            continue
        if "#" in raw:
            desc, role = raw.rsplit("#", 1)
            desc, role = desc.strip(), role.strip().lower()
        else:
            desc, role = raw, "faq"  # 兜底专长
        tasks.append((desc, role))
    tasks = tasks[:6]  # 上限保护
    if not tasks:
        return "未解析出子任务"

    shared_state = shared_state if shared_state is not None else {}
    shared_state.setdefault("subagents", {})

    # 构造 (sid, subagent, task_desc, role) 四元组
    defs = []
    for desc, role in tasks:
        sid = f"sub_{uuid.uuid4().hex[:6]}"
        sub = ReActLoop(
            agent_name=sid,
            tools=get_toolset(role),
            max_steps=4,
            model_tag=f"deepseek-chat(子-{role})",
            role_desc=ROLE_DESC.get(role, "子客服"),
        )
        defs.append((sid, sub, desc, role))

    # 记录派发（拓扑可视化用）—— 用真实 subagent id
    dispatch_info = {
        "subtopics": [f"{d}#{r}" for _, _, d, r in defs],
        "subagent_ids": [sid for sid, _, _, _ in defs],
        "roles": [r for _, _, _, r in defs],
    }
    shared_state.setdefault("dispatches", []).append(dispatch_info)
    if on_dispatch:
        on_dispatch(dispatch_info)

    t0 = time.time()
    results = {}

    def _run_one(sid, sub, desc, role):
        return sid, sub.run(desc, on_step=(
            lambda step, sid=sid: on_subagent_step(sid, step) if on_subagent_step else None))

    if serial:
        for sid, sub, desc, role in defs:
            sid, res = _run_one(sid, sub, desc, role)
            results[sid] = (desc, role, res)
            shared_state["subagents"][sid] = {
                "subtopic": desc, "role": role, "trace": res["trace"],
                "duration": res["duration"], "final_answer": res["final_answer"]}
            if on_subagent_done:
                on_subagent_done(sid, res["duration"], desc)
    else:
        # 并行（核心优势）
        with ThreadPoolExecutor(max_workers=len(defs)) as pool:
            futs = {pool.submit(_run_one, sid, sub, desc, role): sid
                    for sid, sub, desc, role in defs}
            for fut in as_completed(futs):
                sid, res = fut.result()
                desc, role = next((d, r) for s, _, d, r in defs if s == sid)
                results[sid] = (desc, role, res)
                shared_state["subagents"][sid] = {
                    "subtopic": desc, "role": role, "trace": res["trace"],
                    "duration": res["duration"], "final_answer": res["final_answer"]}
                if on_subagent_done:
                    on_subagent_done(sid, res["duration"], desc)

    wall = round(time.time() - t0, 2)
    serial_sum = round(sum(r["duration"] for _, _, r in results.values()), 2)
    shared_state.setdefault("parallel_stats", []).append({
        "n_subagents": len(defs), "wall_clock": wall, "serial_sum": serial_sum,
        "speedup": round(serial_sum / wall, 2) if wall else 0})

    # 汇总文本（喂回主 agent 当 Observation，每个子结果截短防爆 context）
    parts = [f"【子任务: {desc}】({ROLE_DESC.get(role, '子客服')}, 用时{r['duration']}s)\n{r['final_answer'][:500]}"
             for sid, (desc, role, r) in results.items()]
    stats = shared_state["parallel_stats"][-1]
    return (f"并行处理完成：{len(defs)} 个子客服，wall-clock {wall}s "
            f"(串行需 {serial_sum}s，加速 {stats['speedup']}×)\n\n" + "\n\n".join(parts))


def run_customer_service(question: str, on_main_step: Callable = None,
                         on_subagent_step: Callable = None,
                         on_subagent_done: Callable = None,
                         on_dispatch: Callable = None,
                         serial: bool = False) -> dict:
    """执行一次客服会话。返回 {final_answer, main_trace, subagents, parallel_stats, dispatches}。
    serial=True 子客服串行执行（eval A/B 对比基线）。"""
    shared_state = {"subagents": {}, "dispatches": [], "parallel_stats": []}

    def dispatch_tool(action_input, shared_state=None):
        info = shared_state or {}
        return _dispatch_subagents(action_input, shared_state=info,
                                   on_subagent_step=on_subagent_step,
                                   on_subagent_done=on_subagent_done,
                                   on_dispatch=on_dispatch,
                                   serial=serial)

    main = ReActLoop(
        agent_name="main",
        tools={
            "direct_handle": (_direct_handle,
                              "自己直接处理简单单一问题，参数=处理说明"),
            "dispatch_subagents": (dispatch_tool,
                                   "派发多个专长子客服并行处理，参数=用 | 分隔的派单，每条格式: 任务描述#专长(order/after_sale/faq/escalation)"),
        },
        max_steps=8,
        model_tag="deepseek-chat(主)",
        system_prompt=MAIN_SYSTEM,
        role_desc="主客服调度",
    )
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
    q = "帮我查一下订单 A100002 的物流到哪了，给订单 A100003 申请退款原因是商品质量问题，再问下退货政策是什么"
    r = run_customer_service(q)
    print(f"\n{'='*60}\n主客服动作: {[s['action'] for s in r['main_trace']]}")
    print(f"派发次数: {len(r['dispatches'])} | 子客服数: {len(r['subagents'])}")
    print(f"并行统计: {r['parallel_stats']}")
    print(f"\n客服答复:\n{r['final_answer'][:600]}")
