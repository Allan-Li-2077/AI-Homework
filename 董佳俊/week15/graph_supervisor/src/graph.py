"""
Supervisor 编排：route → 分阶段 fan-out → fan-in 聚合

教学重点（教程 P20 三种拓扑 + P21 落地要点）：
  1. 图的语义：节点=异构 worker；边=派发边（supervisor→worker，代码路由决定）
     + 依赖边（worker→worker，数据流）+ 回收边（worker→supervisor）
  2. 分阶段执行：同阶段节点无依赖 → 并行 fan-out（墙钟≈max）；
     跨阶段有依赖 → 等上游 fan-in 后才跑（墙钟=逐段相加）——Amdahl 定律的现场
  3. 聚合：writer 成品直接作最终交付；无 writer 时 supervisor 单次 LLM 聚合
  4. 节点级可观测（P21）：所有事件携带 graph_id，节点事件再带 node_id
  5. 状态可恢复（P21）：--save-trace 把整次运行落盘 JSON（无数据库的最轻量实现）
"""
import copy
import json
import logging
import time
import uuid
from pathlib import Path

import workers as workers_mod
from executor import FEED_LIMIT, build_input, run_stage
from llm_client import llm_chat
from router import route

logger = logging.getLogger(__name__)

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"

SUPERVISOR_SYSTEM = """你是任务主管（supervisor）。你会收到各 subagent 的交付摘要。
请把它们综合成一份结构化报告：分维度组织、要点带依据、末尾给结论与不确定性说明。"""


def run_graph(question: str, on_event=None, serial: bool = False,
              save_trace: bool = False) -> dict:
    """执行一次完整图编排。返回 {graph_id, question, plan, results, final_answer, stats}。
    serial=True 时同阶段节点改串行（eval 基线，凸显并行收益）。"""
    graph_id = uuid.uuid4().hex[:8]

    def emit(ev):
        if on_event:
            on_event({**ev, "graph_id": graph_id})

    # ── 1. 确定性路由：图在 LLM 调用前完全已知 ──
    plan = route(question)
    plan["graph_id"] = graph_id
    emit({"type": "start", "question": question})
    emit({"type": "plan", **plan})

    # ── 2. direct 路径：零派发 ──
    if plan["task_type"] == "direct":
        if plan.get("answer"):
            emit({"type": "final", "answer": plan["answer"], "plan_id": plan["plan_id"]})
            out = {"graph_id": graph_id, "question": question, "plan": plan,
                   "results": {}, "final_answer": plan["answer"],
                   "stats": {"stages": [], "total_wall_clock": 0.0,
                             "total_serial_equiv": 0.0, "total_speedup": 1.0}}
            if save_trace:
                _dump_trace(out)
            emit({"type": "done"})
            return out
        # 零命中 → supervisor 单次 LLM 直答
        emit({"type": "supervisor", "phase": "aggregate_start"})
        answer = llm_chat(SUPERVISOR_SYSTEM, question, temperature=0.0)
        emit({"type": "supervisor", "phase": "aggregate_done"})
        emit({"type": "final", "answer": answer, "plan_id": plan["plan_id"]})
        out = {"graph_id": graph_id, "question": question, "plan": plan,
               "results": {}, "final_answer": answer,
               "stats": {"stages": [], "total_wall_clock": 0.0,
                         "total_serial_equiv": 0.0, "total_speedup": 1.0}}
        if save_trace:
            _dump_trace(out)
        emit({"type": "done"})
        return out

    # ── 3. 分阶段执行：注入 worker 配置（旧坑 #1：显式传 prompt 的根基）──
    # 执行用深拷贝：cfg 里含函数对象不可 JSON 序列化，
    # plan 本身保持干净（已随 plan 事件入 SSE 队列，跨线程共享不能被污染）
    results = {}
    stage_stats = []
    exec_stages = copy.deepcopy(plan["stages"])

    def on_node_event(node_id, ev):
        emit({**ev, "node_id": node_id})

    for i, stage in enumerate(exec_stages):
        for node in stage:
            node["cfg"] = workers_mod.effective_config(node["worker"])
        results, st = run_stage(stage, results, on_node_event, serial=serial)
        st["stage"] = i
        stage_stats.append(st)

    # ── 4. fan-in 聚合 ──
    agg_duration = 0.0
    if plan["aggregate"] == "writer":
        wri_id = next(n["node_id"] for st in exec_stages for n in st
                      if n["worker"] == "writer")
        answer = results[wri_id]["content"]
    else:
        emit({"type": "supervisor", "phase": "aggregate_start"})
        t0 = time.time()
        # 复用 build_input 的结构化拼装（Schema-first，截断防 context 撑爆）
        pseudo = {"depends_on": list(results.keys()), "task_prompt": question}
        material = build_input(pseudo, results)
        answer = llm_chat(SUPERVISOR_SYSTEM, material, temperature=0.0)
        agg_duration = round(time.time() - t0, 2)
        emit({"type": "supervisor", "phase": "aggregate_done"})

    # ── 5. 统计：并行收益量化（聚合段串行，两边都计入 → 诚实的 Amdahl）──
    total_wall = round(sum(s["wall_clock"] for s in stage_stats) + agg_duration, 2)
    total_serial = round(sum(s["serial_sum"] for s in stage_stats) + agg_duration, 2)
    stats = {"stages": stage_stats, "total_wall_clock": total_wall,
             "total_serial_equiv": total_serial,
             "total_speedup": round(total_serial / total_wall, 2) if total_wall else 1.0,
             "aggregate": plan["aggregate"], "aggregate_duration": agg_duration}
    emit({"type": "stats", **stats})
    emit({"type": "final", "answer": answer, "plan_id": plan["plan_id"]})

    out = {"graph_id": graph_id, "question": question, "plan": plan,
           "results": results, "final_answer": answer, "stats": stats}
    if save_trace:
        _dump_trace(out)
    emit({"type": "done"})
    return out


def _dump_trace(out: dict):
    """整次运行落盘：计划 + 每节点 trace + 统计（状态可恢复/回放）。"""
    OUTPUTS_DIR.mkdir(exist_ok=True)
    f = OUTPUTS_DIR / f"trace_{out['graph_id']}.json"
    f.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
                 encoding="utf-8")
    logger.info(f"trace 已落盘: {f.name}")
