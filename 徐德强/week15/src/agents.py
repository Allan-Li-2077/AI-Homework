"""
NBA 赛前模拟分析主 Agent + 并行 Subagent 编排。

主 Agent 负责识别分析需求、拆分子任务并汇总结果；Subagent 分别分析
阵容、球员对位、战术匹配和胜负预测。多个 Subagent 通过线程池并行运行。
"""

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from react_loop import ReActLoop
from tavily_search import format_search_result, nba_search

logger = logging.getLogger(__name__)

VERIFIED_NEWS_CONTEXT = """【已核验新闻底稿，优先级高于模型记忆】
资料截止日期：2026-08-14。

76 人关键变动：
- 虎扑[流言板]援引 Shams：凯尔特人与 76 人达成交易，杰伦-布朗被交易至 76 人；
  凯尔特人得到保罗-乔治、2 个首轮和 2 个次轮。
  来源：https://bbs.hupu.com/640490148.html
- 虎扑[流言板]：76 人官方发文致谢保罗-乔治，确认乔治已离开 76 人。
  来源：https://bbs.hupu.com/640644065.html
- 虎扑[流言板]援引 Shams：勒布朗-詹姆斯 2 年 800 万美元签约 76 人，第二年为球员选项。
  来源：https://bbs.hupu.com/641262326.html
- 虎扑[流言板]：马克西更新社媒欢迎詹姆斯加盟 76 人。
  来源：https://bbs.hupu.com/641259389.html

湖人关键变动：
- 虎扑[流言板]援引 Shams：马蒂斯-赛布尔与湖人达成 1 年 330 万美元合同；
  美媒列出的湖人潜在首发为东契奇、里夫斯、赛布尔、马穆、凯斯勒。
  替补名单线索包括科林-塞克斯顿、昆汀-格兰姆斯、杰克-拉拉维亚、
  贾里德-范德比尔特、凯文-卢尼、布朗尼-詹姆斯、杰登-哈迪、
  道尔顿-克内克特、阿杜-蒂耶罗、扎伊尔-威廉姆斯、卡梅伦-卡尔。
  来源：https://bbs.hupu.com/641114426.html

硬性约束：
- 保罗-乔治不得列为 76 人当前球员，只能作为已离队交易筹码讨论。
- 杰伦-布朗必须列为 76 人核心球员。
- 勒布朗-詹姆斯必须列为 76 人已签约球员。
- 湖人核心分析应围绕东契奇、里夫斯、赛布尔、马穆、凯斯勒等已检索到的新阵容线索展开。
- 如某球员没有上述底稿或搜索结果支持，写入“无法核验”，不要凭记忆补全。
"""

SYNTHESIS_SYSTEM = """你是 NBA 赛前模拟分析主教练。
请根据下面多个专项 Subagent 的研究结果，生成一份中文详细报告。
比赛设定：2026-27 赛季模拟，76 人主场，湖人客场。

{verified_news_context}

重要规则：
- 只使用研究结果中能够被来源或最新 roster 证据支持的球员。
- 如果不同来源冲突，优先采用更新日期更晚、来源更可靠的内容，并说明冲突。
- 不得把 2025-26 赛季旧阵容直接当成 2026-27 当前阵容。
- 阵容核验优先参考球队官方、NBA 官方、虎扑篮球资讯/新闻中标注来源的确定新闻；
  虎扑只使用“虎扑篮球资讯”账号发布的[流言板]/新闻，不使用普通讨论帖作为阵容依据。
- 必须区分已核验事实、合理推断和模拟预测。
- 报告开头写资料截止日期，并说明这是休赛期阵容模拟，不是真实已公布比赛。

报告必须包含：
一、分析前提与资料截止日期
二、76 人和湖人最新已核验阵容
三、核心球员对位
四、战术匹配
五、比赛关键变量
六、胜负预测、概率和比分区间
七、结论、不确定性和来源
"""

SUBAGENT_SYSTEM = """你是 NBA 赛前模拟分析团队中的专项研究员。
你只负责一个子课题：{topic}

比赛背景：2026-27 赛季模拟，76 人主场，湖人客场。

{verified_news_context}

请先使用 web_search 核对 2026 年总决赛之后的最新交易、签约、裁员和官方 roster，
再分析球员对位。不要把 2025-26 赛季预览或历史页面中的旧阵容当成当前阵容。
搜索词必须包含球队名称、2026 休赛期、2026-27 roster 或 latest transactions 等限定词。
优先关注 NBA 官方、球队官网、虎扑篮球资讯/新闻、Basketball-Reference、
ESPN 和 Spotrac 等可靠来源。虎扑只使用“虎扑篮球资讯”账号发布的[流言板]/新闻；
普通专区讨论帖不能作为阵容依据。虎扑内容必须标注 Shams、Marc Stein、ESPN、
球队官方等明确来源后，才能写入“已核验”。
如果搜索结果没有明确证明某球员仍在该队，必须写入“无法核验”，不要凭记忆补全阵容。
专项结论开头先列出“已核验的当前球员”和“无法核验的球员”，再继续分析。
输出时区分：
- 已知数据和来源
- 基于数据的分析
- 需要谨慎对待的假设

最后用中文给出结构化专项结论，供主 Agent 汇总。不要把模拟结论写成确定事实。
"""


def _make_subagent(sid: str, topic: str) -> ReActLoop:
    return ReActLoop(
        agent_name=sid,
        tools={
            "web_search": (
                lambda query, **_: format_search_result(nba_search(query)),
                "联网搜索 NBA 公开资料，参数为查询词",
            )
        },
        max_steps=4,
        model_tag="deepseek-chat(篮球子agent)",
        system_prompt=SUBAGENT_SYSTEM.format(
            topic=topic,
            verified_news_context=VERIFIED_NEWS_CONTEXT,
        ),
        max_tokens=1200,
    )


def _dispatch_subagents(
    action_input: str,
    shared_state: dict | None = None,
    on_subagent_step: Callable | None = None,
    on_subagent_done: Callable | None = None,
    on_dispatch: Callable | None = None,
    serial: bool = False,
) -> str:
    subtopics = [item.strip() for item in action_input.split("|") if item.strip()][:6]
    if not subtopics:
        return "未解析出有效子课题"

    shared_state = shared_state if shared_state is not None else {}
    shared_state.setdefault("subagents", {})
    definitions = []
    for topic in subtopics:
        sid = f"sub_{uuid.uuid4().hex[:6]}"
        definitions.append((sid, _make_subagent(sid, topic), topic))

    dispatch_info = {
        "subtopics": subtopics,
        "subagent_ids": [sid for sid, _, _ in definitions],
    }
    shared_state.setdefault("dispatches", []).append(dispatch_info)
    if on_dispatch:
        on_dispatch(dispatch_info)

    started = time.time()
    results = {}

    def run_one(sid, agent, topic):
        result = agent.run(
            topic,
            on_step=(
                lambda step, sid=sid: on_subagent_step(sid, step)
                if on_subagent_step else None
            ),
        )
        return sid, topic, result

    if serial:
        completed = [
            run_one(sid, agent, topic)
            for sid, agent, topic in definitions
        ]
    else:
        with ThreadPoolExecutor(max_workers=len(definitions)) as pool:
            futures = [
                pool.submit(run_one, sid, agent, topic)
                for sid, agent, topic in definitions
            ]
            completed = [future.result() for future in as_completed(futures)]

    for sid, topic, result in completed:
        results[sid] = (topic, result)
        shared_state["subagents"][sid] = {
            "subtopic": topic,
            "trace": result["trace"],
            "duration": result["duration"],
            "final_answer": result["final_answer"],
        }
        if on_subagent_done:
            on_subagent_done(sid, result["duration"], topic)

    wall_clock = round(time.time() - started, 2)
    serial_sum = round(sum(result["duration"] for _, result in results.values()), 2)
    stats = {
        "n_subagents": len(definitions),
        "wall_clock": wall_clock,
        "serial_sum": serial_sum,
        "speedup": round(serial_sum / wall_clock, 2) if wall_clock else 0,
    }
    shared_state.setdefault("parallel_stats", []).append(stats)

    parts = [
        f"【子课题：{topic}】（用时 {result['duration']}s）\n"
        f"{result['final_answer'][:1600]}"
        for topic, result in results.values()
    ]
    return (
        f"并行分析完成：{len(definitions)} 个 Subagent，"
        f"并行耗时 {wall_clock}s，串行估算 {serial_sum}s，"
        f"阶段加速 {stats['speedup']} 倍。\n\n"
        + "\n\n".join(parts)
    )


def run_research(
    question: str,
    on_main_step: Callable | None = None,
    on_subagent_step: Callable | None = None,
    on_subagent_done: Callable | None = None,
    on_dispatch: Callable | None = None,
    serial: bool = False,
) -> dict:
    shared_state = {"subagents": {}, "dispatches": [], "parallel_stats": []}

    def dispatch_tool(action_input, shared_state=None):
        return _dispatch_subagents(
            action_input,
            shared_state=shared_state,
            on_subagent_step=on_subagent_step,
            on_subagent_done=on_subagent_done,
            on_dispatch=on_dispatch,
            serial=serial,
        )

    # 比赛分析属于明确的多维任务，强制派发，避免模型直接回答而跳过 Subagent。
    required_topics = (
        "核验新闻底稿：杰伦布朗到76人、保罗乔治离开76人、詹姆斯已签约76人 | "
        "核验76人最新阵容：围绕恩比德、马克西、杰伦布朗、詹姆斯，排除保罗乔治 | "
        "核验湖人最新阵容：围绕东契奇、里夫斯、赛布尔、马穆、凯斯勒等虎扑新闻线索 | "
        "76人与湖人核心球员一对一对位：恩比德/马克西/杰伦布朗/詹姆斯 vs 东契奇/里夫斯/凯斯勒 | "
        "两队战术风格、阵容匹配与胜负条件"
    )
    if on_main_step:
        on_main_step({
            "idx": 0,
            "agent": "main",
            "thought": "这是多维 NBA 对战分析，必须先并行核验最新阵容和各专项数据",
            "action": "dispatch_subagents",
            "action_input": required_topics,
            "observation": None,
            "final": False,
        })
    dispatch_observation = _dispatch_subagents(
        required_topics,
        shared_state=shared_state,
        on_subagent_step=on_subagent_step,
        on_subagent_done=on_subagent_done,
        on_dispatch=on_dispatch,
        serial=serial,
    )
    if on_main_step:
        on_main_step({
            "idx": 0,
            "agent": "main",
            "thought": "专项分析已完成，现在由主 Agent 统一汇总",
            "action": "dispatch_subagents",
            "action_input": required_topics,
            "observation": dispatch_observation,
            "done": True,
            "final": False,
        })

    synthesis_prompt = (
        f"用户原始问题：{question}\n\n"
        f"并行专项研究结果：\n{dispatch_observation}"
    )
    main = ReActLoop(
        agent_name="main",
        tools={},
        max_steps=2,
        model_tag="deepseek-chat(篮球主agent)",
        system_prompt=SYNTHESIS_SYSTEM.format(
            verified_news_context=VERIFIED_NEWS_CONTEXT,
        ),
        max_tokens=4096,
    )
    result = main.run(synthesis_prompt, on_step=on_main_step, step_offset=1)
    return {
        "final_answer": result["final_answer"],
        "main_trace": result["trace"],
        "subagents": shared_state["subagents"],
        "parallel_stats": shared_state["parallel_stats"],
        "dispatches": shared_state["dispatches"],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    demo_question = (
        "基于虎扑篮球资讯[流言板]和官方来源，核验杰伦布朗交易至76人、"
        "詹姆斯已签约76人、保罗乔治已离队后的最新阵容，模拟分析"
        "2026-27赛季76人主场对阵湖人的核心球员对位并预测胜负。"
    )
    report = run_research(demo_question)
    print(f"主 Agent 步数：{len(report['main_trace'])}")
    print(f"派发次数：{len(report['dispatches'])}")
    print(f"Subagent 数量：{len(report['subagents'])}")
    print(f"并行统计：{report['parallel_stats']}")
    print(report["final_answer"][:1000])
