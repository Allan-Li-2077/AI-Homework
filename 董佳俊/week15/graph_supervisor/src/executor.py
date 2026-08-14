"""
节点执行器：react / single_shot 双模式 + 并行 / 串行

教学重点：
  1. 有工具节点走 ReAct（Reason + Act）；无工具节点走单次 LLM 调用——
     ReAct 的价值是工具交互，没有工具就没有 Act 环节，循环必然一步结束，
     跑完整循环是过度设计
  2. ThreadPoolExecutor 并行：同阶段节点 wall-clock ≈ max(节点时长)，
     串行基线 = sum(节点时长)——并行收益的量化来源（教程 P21「可并行分支」）
  3. NodeResult 结构化契约（Schema-first 交接）：下游投喂从结构拼装，
     不裸传原始输出；结尾 JSON 块尽力解析，失败兜底不崩
"""
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from llm_client import llm_chat
from react_loop import ReActLoop

logger = logging.getLogger(__name__)

MAX_WORKERS = 4            # 并行度硬保护（教程 P21 落地要点）
FEED_LIMIT = 600           # 下游投喂单节点截断字数（防 context 撑爆）


# ── JSON 块抽取：LLM 格式不稳定防线 ──────────────────────────────────
def _extract_json(text: str) -> dict:
    """从 LLM 输出中尽力抽取结尾 JSON 块，失败兜底 {"summary": 截断全文}。"""
    m = re.search(r"\{[^{}]*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"summary": text[:300]}


# ── 节点输入组装：从 NodeResult 结构化拼装，不裸传原始输出 ────────────
def build_input(node: dict, results: dict) -> str:
    """writer 等有依赖的节点：把 depends_on 的 NodeResult 拼成材料摘要。"""
    if not node["depends_on"]:
        return node["task_prompt"]
    parts = ["以下是上游节点交付的材料摘要："]
    for dep in node["depends_on"]:
        r = results.get(dep)
        if r is None:
            parts.append(f"【{dep}】材料缺失")
        elif r["status"] == "error":
            parts.append(f"【{dep} · {r['label']}】执行失败（内容不可用）")
        else:
            parts.append(f"【{dep} · {r['label']}】(用时 {r['duration']}s)\n"
                         f"{r['content'][:FEED_LIMIT]}")
    parts.append(f"\n{node['task_prompt']}")
    return "\n\n".join(parts)


# ── 单次调用（无工具节点 / 降级模式）──────────────────────────────────
def _run_single_shot(node: dict, cfg: dict, user: str, on_node_event) -> dict:
    """一次 LLM 调用完成节点。生成 1 条合成 step 供可视化与 ReAct 节点对齐。"""
    t0 = time.time()
    content = llm_chat(cfg["system_prompt"], user, temperature=cfg["temperature"],
                       max_tokens=1024)
    trace = [{"idx": 0, "agent": node["node_id"],
              "thought": "(无工具节点：单次调用，无 ReAct 循环)",
              "action": "llm_call", "action_input": user[:60],
              "observation": None, "final": True}]
    on_node_event(node["node_id"], {"type": "node_step", **trace[0]})
    return {"content": content, "trace": trace, "duration": round(time.time() - t0, 2)}


def _run_node(node: dict, cfg: dict, user: str, on_node_event) -> dict:
    """执行单个节点，返回 NodeResult 契约：
    {node_id, worker, label, status, content, structured, trace, duration}"""
    on_node_event(node["node_id"], {"type": "node_start", "worker": node["worker"],
                                    "label": cfg["label"]})
    t0 = time.time()
    try:
        if cfg["mode"] == "react":
            # 旧坑 #1：system_prompt 定义了必须显式传给 ReActLoop，否则用默认模板
            loop = ReActLoop(agent_name=node["node_id"], tools=cfg["tools"],
                             max_steps=cfg["max_steps"],
                             system_prompt=cfg["system_prompt"])
            res = loop.run(user, on_step=lambda s:
                           on_node_event(node["node_id"], {"type": "node_step", **s}))
            content, trace, duration = res["final_answer"], res["trace"], res["duration"]
        else:
            res = _run_single_shot(node, cfg, user, on_node_event)
            content, trace, duration = res["content"], res["trace"], res["duration"]
        status = "ok"
    except Exception as e:
        logger.warning(f"节点 {node['node_id']} 执行失败: {e}")
        content, status = f"节点执行失败: {type(e).__name__}: {str(e)[:120]}", "error"
        trace = [{"idx": 0, "agent": node["node_id"],
                  "thought": "", "action": "error", "action_input": "",
                  "observation": content, "final": True}]
        duration = round(time.time() - t0, 2)

    result = {"node_id": node["node_id"], "worker": node["worker"],
              "label": cfg["label"], "status": status, "content": content,
              "structured": _extract_json(content), "trace": trace,
              "duration": duration}
    on_node_event(node["node_id"], {"type": "node_done", "status": status,
                                    "duration": duration,
                                    "content_preview": content[:80]})
    return result


# ── 阶段执行：同阶段节点并行（或 --serial 串行作基线）─────────────────
def run_stage(stage_nodes: list, results: dict, on_node_event,
              serial: bool = False) -> tuple[dict, dict]:
    """执行一个阶段的所有节点（互相无依赖）。
    返回 (更新后的 results, 阶段统计)。
    统计：wall_clock=并行墙钟，serial_sum=各节点时长之和（串行基线）。"""
    t0 = time.time()
    done = {}

    def one(node):
        cfg = node["cfg"]                    # router 阶段已注入 worker 配置
        user = build_input(node, results)
        return _run_node(node, cfg, user, on_node_event)

    if serial and len(stage_nodes) > 1:
        # 串行基线：for 循环一个接一个（eval A/B 对比用）
        for node in stage_nodes:
            done[node["node_id"]] = one(node)
    else:
        with ThreadPoolExecutor(max_workers=min(len(stage_nodes), MAX_WORKERS)) as pool:
            futs = {pool.submit(one, n): n["node_id"] for n in stage_nodes}
            for fut in as_completed(futs):
                done[futs[fut]] = fut.result()   # _run_node 内部兜底，不会抛

    wall = round(time.time() - t0, 2)
    serial_sum = round(sum(r["duration"] for r in done.values()), 2)
    results.update(done)
    return results, {"n_parallel": len(stage_nodes), "wall_clock": wall,
                     "serial_sum": serial_sum,
                     "speedup": round(serial_sum / wall, 2) if wall else 0.0}


if __name__ == "__main__":
    # 自测：stub 假节点验证并行墙钟 ≈ max(时长) 而非 sum
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    stub_results = {}

    def _stub(node, cfg, user, on_ev):
        delay = 1.5 if node["node_id"] == "res_1" else 2.5
        time.sleep(delay)
        return {"node_id": node["node_id"], "worker": node["worker"],
                "label": cfg["label"], "status": "ok", "content": f"结果({delay}s)",
                "structured": {}, "trace": [], "duration": round(delay, 2)}

    nodes = [{"node_id": "res_1", "worker": "researcher", "depends_on": [], "task_prompt": "x",
              "cfg": {"label": "研究员", "mode": "stub"}},
             {"node_id": "dat_1", "worker": "data_analyst", "depends_on": [], "task_prompt": "y",
              "cfg": {"label": "分析师", "mode": "stub"}}]
    import executor as E
    E._run_node = _stub
    _, stats = E.run_stage(nodes, stub_results, lambda *a: None)
    print(f"stub 并行统计: wall={stats['wall_clock']}s serial_sum={stats['serial_sum']}s "
          f"speedup={stats['speedup']}x（期望 wall≈2.5s，speedup≈1.6x）")
