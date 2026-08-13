"""
主 Agent + 并行 Subagent 编排

教学重点：
  1. 主 agent 自己是 ReAct 循环，有 3 个工具：
     - web_search：单次联网搜索（简单问题直接用）
     - get_weather: 获取指定城市未来时间段的天气预报
     - dispatch_subagents：派发多个 subagent 并行调研（多侧面研究问题用）
     主 agent 根据 query 自行决定用哪个——不是固定拓扑，是 LLM 自主路由
  2. 并行优势凸显：dispatch_subagents 一次派发 N 个 subagent，
     ThreadPoolExecutor 并行跑，wall-clock ≈ max(单agent时长)，
     而非 sum——这就是 subagent 并行的核心价值
  3. 每个 subagent 也是 ReAct 循环（只 web_search 工具），
     trace 全程捕获存入 shared_state，供可视化「点节点看 ReAct 过程」

架构对应 PPT Part 6.3 的 Orchestrator-Workers 拓扑（动态：主 agent 决定派几个）。
"""

import time, logging, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from react_loop import ReActLoop
from tavily_search import tavily_search, format_search_result
from weather_backend import get_weather

logger = logging.getLogger(__name__)

MAIN_SYSTEM = """你是旅游攻略计划者。你有3个工具：
- web_search：联网搜索一次（参数=查询词）。仅用于单一事实可一次答出的问题
- get_weather: 获取目标城市未来时间段的天气预报。（参数=城市、需要查询多少天）
- dispatch_subagents：派发多个子调研员并行调研（参数=用 | 分隔的多个子课题）

【关键决策原则】
- 只要问题涉及 2 个及以上侧面（如「旅游计划」「推荐路线」「游玩攻略」等），
  必须用 dispatch_subagents 把各侧面拆给子调研员并行处理，不要自己串行 web_search 多次。
  示例："长沙未来5天的天气、景点推荐、美食推荐" ->  Action: dispatch_subagents
        Action Input: 长沙未来5天的天气 | 景点推荐 | 美食推荐
- 问题只使用了综合词语，（如「旅游计划」「推荐路线」「游玩攻略」等），考虑景点 | 美食 2 个侧面。
- 只有单一事实问题（如"昆明热门景点有哪些"）才直接 web_search
- 如果调用了天气查询工具，可以结合天气情况来进行推荐景点
- 拿到子整理结果后，根据天数来生成攻略。


【示例】
Question: 广州到昆明未来7天的旅游攻略
Thought: 这是多维度旅游攻略（4个侧面），必须派发子调研员并行收集，不能自己串行搜索
Action: dispatch_subagents
Action Input: 广州到昆明的推荐交通方式 | 昆明未来7天的天气情况 | 昆明及其周边的推荐景点 | 昆明推荐的当地美食
Observation: 并行调查完成：4 个子调查员...（各子课题结果）
Thought: 已收齐四个维度的并行推荐结果，综合成攻略报告
Final Answer: （完整攻略）"""

def _dispatch_subagents(action_input: str, shared_state: dict = None,
                        on_subagent_step: Callable = None,
                        on_subagent_done: Callable = None,
                        on_dispatch: Callable = None) -> str:
    """dispatch_subagents 工具实现。
    action_input: "子课题1 | 子课题2 | ..."（管道分隔）
    派发 N 个 subagent 并行（ThreadPoolExecutor），收齐返回汇总文本。
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
                "web_search": (lambda q, **_: format_search_result(tavily_search(q)),
                               "联网搜索，参数是查询词"),
                "get_weather": (get_weather, "获取目标城市未来时间段的天气预报， \
                                参数=[城市, 天数]")},
            max_steps=4, model_tag="deepseek-chat(子)")
        defs.append((sid, sub, topic))

    # 记录派发（拓扑可视化用：主→N 个子节点）—— 用真实 subagent id
    dispatch_info = {"subtopics": subtopics,
                     "subagent_ids": [sid for sid, _, _ in defs]}
    shared_state.setdefault("dispatches", []).append(dispatch_info)
    if on_dispatch:
        on_dispatch(dispatch_info)   # 真实 id，前端加的节点和后续 subagent_step 对得上

    t0 = time.time()
    results = {}
    # ── 执行：并行(ThreadPool) ──
    def _run_one(sid=sid, sub=sub, topic=topic):
        return sid, sub.run(topic)

    # 并行（凸显 subagent 并行优势的核心）
    with ThreadPoolExecutor(max_workers=len(defs)) as pool:
        futs = {pool.submit(_run_one, sid, sub, topic): sid for sid, sub, topic in defs}
        for fut in as_completed(futs):
            sid, res = fut.result()
            topic = next(t for s, _, t in defs if s == sid)
            results[sid] = (topic, res)
            shared_state["subagents"][sid] = {
                "subtopic": topic, "trace": res["trace"],
                "duration": res["duration"], "final_answer": res["final_answer"]}
            if on_subagent_done:
                on_subagent_done(sid, res["duration"], topic)

    wall = round(time.time() - t0, 2)

    shared_state.setdefault("parallel_stats", []).append({
        "n_subagents": len(defs), "wall_clock": wall
        if wall else 0})

    # 汇总文本（喂回主 agent 当 Observation，每个子结果截短避免主 agent context 过长）
    parts = [f"【子课题: {topic}】(用时{r['duration']}s)\n{r['final_answer']}"
             for sid, (topic, r) in results.items()]
  
    return (f"并行调查完成：{len(defs)} 个子调查员，wall-clock {wall}s "
             + "\n\n".join(parts))


def run_research(question: str, 
                 on_subagent_step: Callable = None,
                 on_subagent_done: Callable = None,
                 on_dispatch: Callable = None) -> dict:
    """执行一次攻略规划。返回 {final_answer, main_trace, subagents, parallel_stats}。
    仅使用并行子调研（ThreadPoolExecutor）。"""
    shared_state = {"subagents": {}, "dispatches": [], "parallel_stats": []}

    def dispatch_tool(action_input, shared_state=None):
        info = shared_state or {}
        # dispatch 事件由 _dispatch_subagents 用真实 subagent id 发出
        # （不能在这里预生成 id，否则和 subagent_step 的 id 对不上）
        return _dispatch_subagents(action_input, shared_state=info,
                                   on_subagent_step=on_subagent_step,
                                   on_subagent_done=on_subagent_done,
                                   on_dispatch=on_dispatch)

    main = ReActLoop(
        agent_name="main",
        tools={
            "web_search": (lambda q, **_: format_search_result(tavily_search(q)),
                           "联网搜索一次，参数=查询词"),
            "get_weather": (get_weather, "获取目标城市未来时间段的天气预报， \
                                            参数=[城市, 天数]"),
            "dispatch_subagents": (dispatch_tool,
                                   "派发多个子调查员并行调查，参数=用 | 分隔的多个子课题"),
        },
        max_steps=8,
        model_tag="deepseek-chat(主)",
        system_prompt=MAIN_SYSTEM,   # ← 传主 agent 的派发引导 prompt
    )
    # 把 shared_state 注入主 agent run
    result = main.run(question, shared_state=shared_state)
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
    q = "广州去北京未来5天的旅游攻略和天气情况"
    r = run_research(q)
    print(f"\n{'='*60}\n主 agent 动作: {[s['action'] for s in r['main_trace']]}")
    print(f"派发次数: {len(r['dispatches'])} | subagent 数: {len(r['subagents'])}")
    print(f"并行统计: {r['parallel_stats']}")
    print(f"\n报告头:\n{r['final_answer']}")