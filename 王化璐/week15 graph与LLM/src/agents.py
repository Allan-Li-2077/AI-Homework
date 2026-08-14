"""
求职公司调研 - 核心 Agent 层
严格仿照 market_research_subagents：主 agent 自主路由 + dispatch_subagents 并行派发
融合 GraphRAG：新增第 3 个工具 store_to_graph，调研完后持久化到 Neo4j
"""
from __future__ import annotations

import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import llm_client
from src.react_loop import ReActLoop, StepEvent
from src.tavily_search import web_search, format_search_result
from src.extract_triples import extract_from_text, save_triples, TripleBatch
from src.build_graph import (
    get_driver as neo4j_get_driver, ensure_constraints, build_in_neo4j, main as build_graph_main
)
from src.retrieve import check_company_exists, search_via_graph


# ============================================================
# Subagent 系统提示词（某一具体侧面的联网调研员）
# ============================================================
SUBAGENT_SYSTEM = """你是一名专门做【求职公司特定侧面】调研的 Subagent（子调研员）。
请严格遵循 ReAct 格式输出（一行 Thought/一行 Action/一行 Action Input/等待 Observation 再继续）：

```
Thought: <我现在需要什么信息>
Action: web_search
Action Input: <搜索关键词>
```
（循环若干轮）
最后，当你有了足够信息后，必须以如下格式收尾：
```
Thought: 我现在有足够信息给出总结了。
Final Answer: <结构化总结，带数据、来源要点，300-600 字>
```

【工具】：只有一个 `web_search`（联网搜索）。
【要求】：
1. 只调研你被分配的那个**单一侧面**，不要跑题到其他侧面。
2. 最终答案必须是**结构化文字总结**，分点列出要点、关键数字、公开来源关键词（如"看准网2024薪资报告"）。
3. 不要跟用户交互，不要输出额外说明，你是后台子 agent。
"""


# ============================================================
# Main Agent 系统提示词（自主路由：直搜 / 派发 / 存图）
# ============================================================
MAIN_SYSTEM = """你是一名求职公司调研的总调度 Agent（主调研员）。
你有 3 个工具：web_search、dispatch_subagents、store_to_graph。

严格遵循 ReAct 格式输出：
```
Thought: <我的分析与下一步决策>
Action: <工具名>
Action Input: <工具入参>
```
多次循环后，最终必须给出 Final Answer：
```
Thought: 我现在可以综合所有信息给用户报告。
Final Answer: <完整求职调研报告，分章节>
```

【决策原则】
1. 单一简单事实（"字节跳动CEO是谁"这种）→ 直接 `web_search`。
2. 用户提出的是多维度/多侧面的公司调研（例如包含"业务/薪资/面试/技术栈/前景"中任意 2 个以上关键词）→ **必须调用 `dispatch_subagents`**，把各侧面拆成独立子任务并行调研，绝对不能自己一个人搜。
   - dispatch_subagents 的 Action Input 格式：用 `|` 分隔多个子课题，每个子课题写清「公司名 + 具体侧面」，例如：
     "字节跳动 主营业务与业务板块 | 字节跳动 薪资待遇与福利（看准网/脉脉） | 字节跳动 面试流程经验与面经（牛客） | 字节跳动 技术栈与工程文化 | 字节跳动 发展前景行业口碑"
   - 最多派 5 个 subagent，够用就行。
3. 只要你完成了一个多侧面调研（dispatch_subagents 返回了结果），**综合报告输出前必须调用 `store_to_graph`**，Action Input 就写"当前公司名"（例如 "字节跳动"）。这个工具会把调研结果结构化地存入知识图谱，下次查询可直接复用。

【示例（学习格式）】
Question: 请帮我做字节跳动的求职调研：业务、薪资、面试、技术栈、前景
Thought: 这是一个典型的多维度求职调研（5个侧面），必须派发多个子调研员并行收集信息才能全面，不能自己一个搜。
Action: dispatch_subagents
Action Input: 字节跳动 主营业务与业务板块 | 字节跳动 薪资待遇与福利（看准网/脉脉2024） | 字节跳动 面试流程经验与面经（牛客） | 字节跳动 技术栈与工程文化 | 字节跳动 发展前景行业口碑与员工评价
（...Observation 返回 5 个子任务总结...）
Thought: 已经收集到 5 个侧面的汇总信息。接下来先把调研结果存入知识图谱方便下次复用，然后综合成报告。
Action: store_to_graph
Action Input: 字节跳动
（...Observation: "[store_to_graph] 已为字节跳动抽取实体N个/关系M个，存入 Neo4j" ...）
Thought: 好，存图完成。现在综合所有侧面信息输出 Final Answer。
Final Answer: 【字节跳动求职调研报告】......

【工具清单再强调一遍】
- web_search          Action Input: 搜索关键词（字符串）
- dispatch_subagents  Action Input: 子课题1 | 子课题2 | ... （用 | 分隔）
- store_to_graph      Action Input: 公司名（字符串，例如 "字节跳动"）
"""


@dataclass
class RunTrace:
    """聚合主 agent + 所有 subagent 的运行数据，用于 serve.py 推送 + eval 统计"""
    main_steps: list[StepEvent] = field(default_factory=list)
    sub_results: list[dict] = field(default_factory=list)  # [{name, final_answer, steps, total_ms}]
    final_answer: str = ""
    parallel: dict = field(default_factory=dict)           # {wall_ms, serial_sum_ms, speedup}
    graph_info: dict = field(default_factory=dict)         # {from_graph, triples, answer, ms}
    total_ms: int = 0

    def to_dict(self):
        return {
            "main_steps": [s.__dict__ for s in self.main_steps],
            "sub_results": self.sub_results,
            "final_answer": self.final_answer,
            "parallel": self.parallel,
            "graph_info": self.graph_info,
            "total_ms": self.total_ms,
        }


class ResearchAgents:
    """
    对外总入口。
    - research(question) → 走主 agent ReAct，可能派发 subagent，可能存图。
    - research_or_query(company_name, question) → 【融合版】先查 Neo4j，有就直接用，没有再调研。
    """

    def __init__(self, event_cb: Callable[[dict], None] | None = None,
                 serial: bool = False):
        """
        event_cb: 每发生一个事件（主 step / 派发 / 子 step / 完成 / 存图）都回调，用于 SSE
        serial:   True 时 dispatch_subagents 退化为 for 循环串行（用于 eval A/B 对比）
        """
        self.event_cb = event_cb
        self.serial = serial
        # 派发结果缓存：主 agent 在同一次 ReAct 里用 dispatch_id 查结果
        self._dispatch_results: dict[str, dict] = {}
        self._dispatch_lock = threading.Lock()
        # 最近一次 subagent 调研文本累积（供 store_to_graph 工具用）
        self._last_subagent_summaries: list[tuple[str, str]] = []  # (子课题名, 总结文本)

    # ---------- 工具定义 ----------
    def _tool_web_search(self, q: str) -> str:
        res = web_search(q)
        return format_search_result(res)

    def _tool_dispatch_subagents(self, topics_str: str) -> str:
        """
        入参："课题1 | 课题2 | 课题3"（用 | 分隔）
        实现：每个课题起一个 subagent（ReActLoop 实例，只有 web_search）
              ThreadPoolExecutor 并行 → 汇总字符串 → 作为 Observation 塞回主 agent
        """
        topics = [t.strip() for t in topics_str.split("|") if t.strip()]
        topics = topics[:5]  # 安全上限
        if not topics:
            return "[dispatch_subagents] 错误：没有子课题，请用 | 分隔多个子课题。"

        summaries: dict[str, str] = {}
        per_stats: list[dict] = []
        wall_t0 = time.perf_counter()

        def run_one(topic: str) -> tuple[str, str, dict]:
            role = "sub_" + "".join(c if c.isalnum() else "_" for c in topic[:16])
            tools = {"web_search": self._tool_web_search}

            def sub_evt_cb(evt: StepEvent):
                evt.role = role
                if self.event_cb:
                    self.event_cb({"kind": "subagent_step", "event": evt.__dict__})

            loop = ReActLoop(system=SUBAGENT_SYSTEM, tools=tools,
                             role=role, max_steps=8, event_cb=sub_evt_cb)
            if self.event_cb:
                self.event_cb({"kind": "dispatch_start", "subagent": role, "topic": topic})
            r = loop.run(topic)
            return topic, r.final_answer, {"name": role, "final_answer": r.final_answer,
                                           "step_count": len(r.steps), "total_ms": r.total_ms,
                                           "steps": [s.__dict__ for s in r.steps]}

        if self.serial:
            # 串行：for 循环（eval 基线用）
            results = [run_one(t) for t in topics]
        else:
            # 并行：ThreadPool
            results = []
            with ThreadPoolExecutor(max_workers=len(topics)) as ex:
                futs = {ex.submit(run_one, t): t for t in topics}
                for fut in as_completed(futs):
                    results.append(fut.result())

        wall_ms = int((time.perf_counter() - wall_t0) * 1000)
        serial_sum_ms = sum(int(r[2]["total_ms"]) for r in results)
        speedup = (serial_sum_ms / wall_ms) if wall_ms > 0 else 1.0

        for topic, fa, stat in results:
            summaries[topic] = fa
            per_stats.append(stat)

        # 缓存起来：后续 store_to_graph 工具直接拿这些文本去抽三元组
        self._last_subagent_summaries = [(t, summaries[t]) for t in topics]

        if self.event_cb:
            self.event_cb({"kind": "dispatch_done",
                           "wall_ms": wall_ms, "serial_sum_ms": serial_sum_ms,
                           "speedup_x": round(speedup, 2),
                           "subagents": per_stats})

        # 汇总 Observation 文本：每个子课题一段
        lines = [f"【dispatch_subagents 完成】并行墙钟 {wall_ms}ms；串行总和 {serial_sum_ms}ms；加速比 {speedup:.2f}x"]
        for t in topics:
            lines.append(f"\n===== 子课题：{t} =====\n{summaries[t]}")
        return "\n".join(lines)

    def _tool_store_to_graph(self, company_name: str) -> str:
        """
        把最近一次 dispatch_subagents 得到的总结文本 → 抽三元组 → 存 JSON → MERGE 进 Neo4j。
        这一步是把 GraphRAG 项目的 extract_triples.py + build_graph.py 串起来。
        """
        if not self._last_subagent_summaries:
            return "[store_to_graph] 警告：没有可用的子调研结果，请先调用 dispatch_subagents。"
        company_name = (company_name or "").strip() or "UnknownCompany"
        batches: list[TripleBatch] = []
        ent_count, rel_count = 0, 0
        t0 = time.perf_counter()

        try:
            for topic, summary in self._last_subagent_summaries:
                source = f"{company_name}_{topic[:20]}"
                batch = extract_from_text(source, summary)
                batches.append(batch)
                ent_count += len(batch.entities)
                rel_count += len(batch.relations)

            # 1) 写到 data/company_triples.json（持久化备份）
            save_triples(batches)

            # 2) MERGE 进 Neo4j
            driver = neo4j_get_driver()
            ensure_constraints(driver)
            stats = build_in_neo4j(
                driver,
                [e for b in batches for e in b.entities],
                [r for b in batches for r in b.relations],
            )
            driver.close()
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"[store_to_graph] 失败：{type(e).__name__}: {e}"

        total_ms = int((time.perf_counter() - t0) * 1000)
        msg = (f"[store_to_graph] 成功：公司「{company_name}」→ 抽实体 {ent_count} 个 / "
               f"关系 {rel_count} 条 → Neo4j 合并完成（当前图谱 {stats.get('total_nodes','?')} 节点 / "
               f"{stats.get('total_edges','?')} 边，耗时 {total_ms}ms）")
        if self.event_cb:
            self.event_cb({"kind": "graph_stored", "company": company_name,
                           "entities": ent_count, "relations": rel_count,
                           "elapsed_ms": total_ms,
                           "neo4j": stats})
        return msg

    # ---------- 主入口 ----------
    def research(self, question: str) -> RunTrace:
        """走主 agent ReAct 循环：直搜 / 派发 / 存图，全程自主路由"""
        t0 = time.perf_counter()
        trace = RunTrace()

        def main_evt_cb(evt: StepEvent):
            trace.main_steps.append(evt)
            if self.event_cb:
                self.event_cb({"kind": "main_step", "event": evt.__dict__})

        tools = {
            "web_search": self._tool_web_search,
            "dispatch_subagents": self._tool_dispatch_subagents,
            "store_to_graph": self._tool_store_to_graph,
        }
        loop = ReActLoop(system=MAIN_SYSTEM, tools=tools,
                         role="main", max_steps=15, event_cb=main_evt_cb)
        result = loop.run(question)

        # 统计并行信息（从 steps 里找 dispatch 的 Observation 摘要）
        for s in trace.main_steps:
            if "dispatch_subagents 完成" in s.observation:
                import re as _re
                mw = _re.search(r"并行墙钟\s*(\d+)ms", s.observation)
                sm = _re.search(r"串行总和\s*(\d+)ms", s.observation)
                sp = _re.search(r"加速比\s*([0-9.]+)x", s.observation)
                if mw and sm:
                    trace.parallel = {
                        "wall_ms": int(mw.group(1)),
                        "serial_sum_ms": int(sm.group(1)),
                        "speedup_x": float(sp.group(1)) if sp else None,
                    }
                    break
        trace.final_answer = result.final_answer
        trace.total_ms = int((time.perf_counter() - t0) * 1000)
        if self.event_cb:
            self.event_cb({"kind": "done", "final_answer": trace.final_answer,
                           "total_ms": trace.total_ms})
        return trace

    def research_or_query(self, company_name: str, question: str) -> RunTrace:
        """
        融合入口：先查图谱 → 有就直接用；没有就走 research() 并行调研并存图。
        """
        t0 = time.perf_counter()
        trace = RunTrace()
        try:
            driver = neo4j_get_driver()
            in_graph = check_company_exists(driver, company_name)
        except Exception as e:
            in_graph = False
            if self.event_cb:
                self.event_cb({"kind": "warn", "msg": f"Neo4j 不可用，降级为纯调研: {e}"})
            driver = None

        if in_graph and driver:
            if self.event_cb:
                self.event_cb({"kind": "graph_hit", "company": company_name,
                               "msg": f"「{company_name}」已在知识图谱中，直接图检索"})
            res = search_via_graph(driver, company_name, question)
            trace.graph_info = res
            trace.final_answer = res["answer"] + f"\n\n⚠️ 【检索方式】知识图谱命中，耗时 {res['elapsed_ms']}ms，子图三元组 {res['subgraph_triples']} 条。"
            trace.total_ms = int((time.perf_counter() - t0) * 1000)
            driver.close()
            return trace

        # 图谱没有 -> 走正常调研
        if self.event_cb:
            self.event_cb({"kind": "graph_miss", "company": company_name,
                           "msg": f"「{company_name}」不在图谱中，启动并行调研..."})
        return self.research(f"{company_name} 求职调研：{question}")


# 纯命令行跑一遍自测（python -m src.agents）
if __name__ == "__main__":
    # 没装 dotenv 就忽略，靠系统环境变量
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    agents = ResearchAgents(serial=False)

    # 方式一：直接 research（不经过图谱先查）
    # trace = agents.research("请帮我做字节跳动的求职调研：业务、薪资、面试、技术栈、前景")

    # 方式二：融合 research_or_query（推荐！先查 Neo4j，命中就直接答，没命中才调研并存图）
    trace = agents.research_or_query("字节跳动", "业务板块、薪资待遇、技术栈、面试流程、行业前景")

    print("\n======== FINAL ANSWER ========\n")
    print(trace.final_answer)
    print(f"\n总耗时: {trace.total_ms} ms")
    if trace.parallel:
        print(f"并行加速: {trace.parallel}")
    if trace.graph_info:
        print(f"图谱命中: {trace.graph_info}")
