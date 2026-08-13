"""
子 agent 派发引擎（独立模块）

职责：
  1. 解析主 agent 的派发参数 "角色:子课题 | 角色:子课题"
  2. 为每个子课题创建子 agent（ReActLoop + web_search，全员联网）
  3. ThreadPoolExecutor 并行执行（serial=True 时退化为 for 循环，eval 基线）
  4. 汇总子结果（截短）喂回主 agent 当 Observation，量化并行加速

设计：不依赖 agents.py——角色池作为参数传入，保持通用性。
     任何主 agent 都能用 DispatchEngine 派发。
"""
import time, uuid, logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from react_loop import ReActLoop
from bocha_search import bocha_search, format_search_result

logger = logging.getLogger(__name__)


class DispatchEngine:
    """派发引擎：解析子课题 → 并行跑 N 个子 agent ReAct → 汇总文本。"""

    def __init__(self, subagent_roles: dict, serial: bool = False,
                 max_subagents: int = 6):
        """
        subagent_roles: {role: {"name": 角色名, "system_prompt": 角色提示词}}
        serial: True 时子 agent 串行执行（对比并行的基线）
        max_subagents: 派发数量上限保护
        """
        self.subagent_roles = subagent_roles
        self.serial = serial
        self.max_subagents = max_subagents

    def parse_targets(self, action_input: str) -> list[tuple[str, str]]:
        """解析 "角色:子课题 | 角色:子课题"，未知角色回退 general。
        返回 [(role, topic), ...]，上限 max_subagents 个。"""
        targets = []
        for part in action_input.split("|"):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                role, topic = part.split(":", 1)
                role, topic = role.strip(), topic.strip()
                if role not in self.subagent_roles:
                    role = "general"
            else:
                role, topic = "general", part
            if topic:
                targets.append((role, topic))
        return targets[:self.max_subagents]

    def dispatch(self, action_input: str, shared_state: dict = None,
                 on_subagent_step: Callable = None,
                 on_subagent_done: Callable = None,
                 on_dispatch: Callable = None) -> str:
        """派发执行，返回汇总文本（喂回主 agent 当 Observation）。
        shared_state: 塞入 subagents/dispatches/parallel_stats 供 CLI 与 trace 使用。"""
        targets = self.parse_targets(action_input)
        if not targets:
            return "未解析出子课题"
        shared_state = shared_state if shared_state is not None else {}
        shared_state.setdefault("subagents", {})
        shared_state.setdefault("dispatches", [])
        shared_state.setdefault("parallel_stats", [])

        # 构造 (sid, role, topic, subagent) —— 子 agent 全部 ReAct + 全部联网
        defs = []
        for role, topic in targets:
            sid = f"sub_{uuid.uuid4().hex[:6]}"
            role_info = self.subagent_roles[role]
            sub = ReActLoop(
                agent_name=sid,
                tools={"web_search": (
                    lambda q, **_: format_search_result(bocha_search(q)),
                    "搜索一次，参数=查询词")},
                max_steps=4,
                model_tag=f"deepseek-chat({role_info['name']})",
                system_prompt=role_info["system_prompt"],
            )
            defs.append({"sid": sid, "sub": sub, "role": role, "topic": topic})

        # 记录派发（用真实 sid，CLI 打印与后续 step 对得上）
        dispatch_info = {"subtopics": [d["topic"] for d in defs],
                         "roles": [d["role"] for d in defs],
                         "subagent_ids": [d["sid"] for d in defs]}
        shared_state["dispatches"].append(dispatch_info)
        if on_dispatch:
            on_dispatch(dispatch_info)

        t0 = time.time()
        results = {}

        def _run_one(d):
            return d["sid"], d["sub"].run(d["topic"], on_step=(
                lambda step, sid=d["sid"]: on_subagent_step(sid, step)
                if on_subagent_step else None))

        if self.serial:
            # 串行：一个接一个（eval A/B 对比基线）
            for d in defs:
                sid, res = _run_one(d)
                results[sid] = (d["role"], d["topic"], res)
                shared_state["subagents"][sid] = {
                    "role": d["role"], "subtopic": d["topic"],
                    "trace": res["trace"], "duration": res["duration"],
                    "final_answer": res["final_answer"]}
                if on_subagent_done:
                    on_subagent_done(sid, res["duration"], d["topic"])
        else:
            # 并行：ThreadPoolExecutor（凸显 subagent 并行的核心价值）
            with ThreadPoolExecutor(max_workers=len(defs)) as pool:
                futs = {pool.submit(_run_one, d): d["sid"] for d in defs}
                for fut in as_completed(futs):
                    sid, res = fut.result()
                    d = next(x for x in defs if x["sid"] == sid)
                    results[sid] = (d["role"], d["topic"], res)
                    shared_state["subagents"][sid] = {
                        "role": d["role"], "subtopic": d["topic"],
                        "trace": res["trace"], "duration": res["duration"],
                        "final_answer": res["final_answer"]}
                    if on_subagent_done:
                        on_subagent_done(sid, res["duration"], d["topic"])

        # 并行量化：wall_clock（并行墙钟） vs serial_sum（串行基线）
        wall = round(time.time() - t0, 2)
        serial_sum = round(sum(r[2]["duration"] for r in results.values()), 2)
        shared_state["parallel_stats"].append({
            "n_subagents": len(defs), "wall_clock": wall, "serial_sum": serial_sum,
            "speedup": round(serial_sum / wall, 2) if wall else 0})

        # 汇总文本（每个子结果截短，防主 agent context 撑爆）
        parts = [
            f"【角色: {role} | 子课题: {topic}】(用时{dur}s)\n{ans[:500]}"
            for _, (role, topic, res) in results.items()
            for dur, ans in [(res["duration"], res["final_answer"])]
        ]
        stats = shared_state["parallel_stats"][-1]
        return (f"并行调研完成：{len(defs)} 个子调研员，wall-clock {wall}s "
                f"(串行需 {serial_sum}s，加速 {stats['speedup']}×)\n\n" + "\n\n".join(parts))


if __name__ == "__main__":
    # 自测：手动派发两个 general 子课题
    import logging as _l
    _l.basicConfig(level=_l.WARNING)
    _roles = {"general": {"name": "综合研究员",
                          "system_prompt": "你是综合研究员。每轮输出一个 JSON 对象（json 格式）："
                                           '{{"thought": "...", "action": "web_search", '
                                           '"action_input": "查询词"}} 或 '
                                           '{{"thought": "...", "final_answer": "..."}}。'}}
    eng = DispatchEngine(_roles)
    out = eng.dispatch("2024年中国GDP总量 | 2025年春节档电影票房")
    print(out[:600])
    print("\n并行统计:", eng and out and "见上方汇总")
