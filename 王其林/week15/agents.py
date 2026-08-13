"""
主 Agent + 子 Agent 角色池编排（通用问答场景）

架构：
  - 主 agent：ReAct 架构，2 个工具（web_search 自己联网 + dispatch_subagents 派发），
    根据问题自主路由：单一事实直接搜索，多侧面问题派发子 agent 并行调研
  - 子 agent 池：finance/tech/news/general 四个专业角色，
    全部 ReAct 架构 + web_search（全员联网），由 DispatchEngine 并行执行
  - 派发逻辑独立在 dispatcher.py（本文件只做配置与组装）

范式归属：动态 Orchestrator-Workers——主 agent 决定派几个、派什么角色。
"""
import logging

from react_loop import ReActLoop
from bocha_search import bocha_search, format_search_result
from dispatcher import DispatchEngine

logger = logging.getLogger(__name__)

# ── 子 agent 角色池：只写角色差异（定位+调研规范），JSON 协议由 REACT_SYSTEM 提供 ──
SUBAGENT_ROLES = {
    "finance": {
        "name": "财经分析师",
        "system_prompt": "你是财经分析师（宏观/财报/投资）。搜索权威来源（统计局/央行/财报公告/主流财经媒体）；数字注明时间与来源；数据缺失明说，不编造。",
    },
    "tech": {
        "name": "科技专家",
        "system_prompt": "你是科技专家（AI/半导体/技术趋势）。优先权威来源（论文/公司官网/知名科技媒体）；区分事实与观点；信息过时主动搜索更新。",
    },
    "news": {
        "name": "新闻记者",
        "system_prompt": "你是时事记者（热点/政策/社会新闻）。优先时效性强的来源并注明时间；多来源交叉验证；区分事实与评论。",
    },
    "general": {
        "name": "综合研究员",
        "system_prompt": "你是综合研究员（任何领域）。先搜权威来源再组织答案；多角度覆盖；结论注明不确定性。",
    },
}

# ── 主 agent 前缀提示：决策原则 + 精简示例（JSON 协议由 REACT_SYSTEM 提供）──
MAIN_SYSTEM = """你是通用问答主分析师。
- 单一事实问题 → web_search（参数=查询词）
- 2+ 侧面问题（调研/分析/对比/概况）→ 必须 dispatch_subagents，参数="角色:子课题 | 角色:子课题"
角色：finance 财经（宏观/财报/投资）、tech 科技（AI/半导体/技术）、news 新闻（时事/政策）、general 综合
收齐子结果后综合成报告：分维度、每点带来源、末尾给结论与不确定性

格式示例（严格照此输出）：
{"thought": "多侧面，派发子调研员", "action": "dispatch_subagents", "action_input": "tech:市场规模 | tech:技术趋势 | finance:上市公司"}"""

# 多侧面关键词：命中时注入派发引导（规则兜底，不依赖 prompt 决策）
MULTI_ANGLE_KEYWORDS = ["调研", "分析", "对比", "概况", "趋势", "竞争", "评估", "怎么看待"]


def run_research(question: str, on_main_step=None, on_subagent_step=None,
                 on_subagent_done=None, on_dispatch=None, serial: bool = False) -> dict:
    """执行一次通用问答。返回 {final_answer, main_trace, subagents, parallel_stats, dispatches}。
    serial=True 时子 agent 串行执行（eval A/B 对比基线）。"""
    shared_state = {"subagents": {}, "dispatches": [], "parallel_stats": []}
    engine = DispatchEngine(SUBAGENT_ROLES, serial=serial)

    # 规则兜底：多侧面关键词命中时注入软引导（防该派发不派发，仅命中时多花 ~40 字）
    if any(k in question for k in MULTI_ANGLE_KEYWORDS):
        question = question + "\n\n（提示：此问题可能涉及多个方面，请优先用 dispatch_subagents 拆分调研）"

    def dispatch_tool(action_input, shared_state=None):
        info = shared_state or {}
        return engine.dispatch(action_input, shared_state=info,
                               on_subagent_step=on_subagent_step,
                               on_subagent_done=on_subagent_done,
                               on_dispatch=on_dispatch)

    main = ReActLoop(
        agent_name="main",
        tools={
            "web_search": (lambda q, **_: format_search_result(bocha_search(q)),
                           "搜索一次，参数=查询词"),
            "dispatch_subagents": (
                dispatch_tool,
                "派发子调研员并行，参数=角色:子课题|角色:子课题"),
        },
        max_steps=8,
        model_tag="deepseek-chat(主)",
        system_prompt=MAIN_SYSTEM,
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
    q = "分析2025年中国AI行业：市场规模、技术趋势、主要公司"
    r = run_research(q)
    print(f"\n{'=' * 60}\n主 agent 动作: {[s['action'] for s in r['main_trace']]}")
    print(f"派发次数: {len(r['dispatches'])} | subagent 数: {len(r['subagents'])}")
    print(f"并行统计: {r['parallel_stats']}")
    print(f"\n报告头:\n{r['final_answer'][:200]}")
