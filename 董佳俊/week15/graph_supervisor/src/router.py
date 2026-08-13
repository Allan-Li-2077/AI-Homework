"""
确定性路由：Python 规则定边，LLM 零参与

教学重点（教程 P20「代码定边、模型定节点内」）：
  1. 整张 agent 拓扑由纯 Python 函数 route() 决定——可单测、可审计、可复现，
     不依赖 LLM 的「自觉」，也不怕它不按套路出牌
  2. 路由完成时图就完全已知：stages/edges 先于任何 LLM 调用产生，
     前端拿到 plan 事件即可预画整张 DAG（对比旧项目：LLM 派发时图才生长）
  3. LLM 只在「节点内」干活——worker 用 ReAct/单次调用完成自己的子任务，
     不参与决定「派不派、派给谁」

路由规则（三级）：
  问候语 → direct（零派发，静态回复）
  命中 1 类关键词 → single（派 1 个对应 worker）
  命中 ≥2 类 → dag（两阶段：可并行的先并行 fan-out，依赖它们的后跑 fan-in）
  零命中 → direct_llm（supervisor 单次 LLM 兜底直答）
"""
import uuid

import workers as workers_mod

# 类别关键词：命中即派发对应 worker（纯规则）
CATEGORY_KEYWORDS = {
    "research": ["调研", "研究", "行业", "市场", "现状", "趋势", "政策",
                 "竞争", "格局", "概况", "渗透率", "发展", "前景"],
    "data": ["算一算", "计算", "增速", "增长率", "cagr", "年均", "同比",
             "占比", "合计", "亿元", "万元", "%", "翻倍", "涨了"],
    "writing": ["写一篇", "撰写", "文案", "推文", "公众号", "广告语",
                "演讲稿", "策划方案", "文章", "报告", "宣传"],
}

# 问候/闲聊关键词：直接静态回复，一条 LLM 调用都不花（确定性审批门）
DIRECT_REPLIES = {
    "greet": ("你好！我是图编排 Supervisor。我可以派发多个 subagent 并行干活："
              "调研行业、计算数据、撰写文案。复合任务会自动拆解并行处理，试试问我一个调研+计算+写作的问题吧。"),
}

_WORKER_PREFIX = {"researcher": "res", "data_analyst": "dat", "writer": "wri"}
# 类别命中顺序：决定 stage1 内节点排列
_CATEGORY_ORDER = ["research", "data", "writing"]
# 类别名 → worker 名（注册表键）
_CATEGORY_TO_WORKER = {"research": "researcher", "data": "data_analyst",
                       "writing": "writer"}


def _detect_hits(question: str) -> list[str]:
    """按固定顺序返回命中的类别列表。"""
    return [cat for cat in _CATEGORY_ORDER
            if any(k in question.lower() for k in CATEGORY_KEYWORDS[cat])]


def _build_node(worker: str, task_prompt: str, depends_on: list, idx: int) -> dict:
    """构造 node 契约（Schema-first：字段固定，下游不靠猜）。"""
    cfg = workers_mod.effective_config(worker)
    return {
        "node_id": f"{_WORKER_PREFIX[worker]}_{idx}",
        "worker": worker,
        "label": workers_mod.WORKERS[worker]["label"],
        "color": workers_mod.WORKERS[worker]["color"],
        "shape": workers_mod.WORKERS[worker]["shape"],
        "mode": cfg["mode"],            # 实际执行模式（无 key 时 researcher 为 single_shot）
        "task_prompt": task_prompt,
        "depends_on": depends_on,
    }


def _task_prompt(question: str, worker: str, is_single: bool) -> str:
    """按 worker 类别生成子任务描述，多 worker 时加「只做自己的部分」指令。"""
    if worker == "researcher":
        return (f"调研课题：{question}"
                if is_single else
                f"原始问题：{question}\n\n【你的任务】只完成其中的调研部分："
                f"梳理现状/格局/趋势等要点，带数据支撑。不要写整篇成品文案，不要做数值计算。")
    if worker == "data_analyst":
        return (f"计算任务：{question}"
                if is_single else
                f"原始问题：{question}\n\n【你的任务】只完成其中的数值计算部分："
                f"把题中给定的数据用 calculator 工具算出要求的指标（增速/CAGR 等），给出每步计算过程。")
    # writer
    return (f"写作任务：{question}"
            if is_single else
            f"写作任务：{question}\n\n【你的任务】基于下方提供的调研与数据材料摘要，"
            f"撰写题目要求的成品文案。字数、文风、读者按题目要求，只写材料里有依据的内容。")


def route(question: str) -> dict:
    """确定性路由：纯函数，同一输入永远得到同一张图。
    返回 TaskPlan 契约（主→子交接，Schema-first）：
    {plan_id, task_type, search_mode, stages, edges, aggregate, route_note, ...}
    """
    q = question.strip()
    plan_id = uuid.uuid4().hex[:8]

    # ── 路径 1：问候语 → 零派发静态回复 ──
    lowered = q.lower()
    if any(k in lowered for k in ["你好", "您好", "hello", "hi", "谢谢", "再见",
                                  "你是谁", "在吗", "你是谁呀"]):
        return {"plan_id": plan_id, "task_type": "direct",
                "answer": DIRECT_REPLIES["greet"], "stages": [], "edges": [],
                "aggregate": "none",
                "route_note": "命中问候关键词 → 零派发、零 LLM 调用，静态回复（确定性审批门）"}

    hits = [_CATEGORY_TO_WORKER[c] for c in _detect_hits(q)]

    # ── 路径 2：零命中 → supervisor 单次 LLM 直答 ──
    if not hits:
        return {"plan_id": plan_id, "task_type": "direct", "direct_llm": True,
                "stages": [], "edges": [], "aggregate": "supervisor",
                "route_note": "未命中任何 worker 类别 → 不派发，supervisor 单次 LLM 直答"}

    search_mode = "tavily" if workers_mod.SEARCH_AVAILABLE else "knowledge"

    # ── 路径 3：命中 1 类 → 派 1 个 worker ──
    if len(hits) == 1:
        worker = hits[0]
        node = _build_node(worker, _task_prompt(q, worker, is_single=True), [], 1)
        return {"plan_id": plan_id, "task_type": "single", "search_mode": search_mode,
                "stages": [[node]],
                "edges": [["supervisor", node["node_id"], "dispatch"],
                          [node["node_id"], "supervisor", "return"]],
                "aggregate": "supervisor",
                "route_note": f"命中 {node['label']} 关键词 → 单 worker：只派 1 个{node['label']}"}

    # ── 路径 4：命中 ≥2 类 → 两阶段 DAG ──
    # stage1：research/data 中命中的，相互独立 → 并行 fan-out
    # stage2：writing 命中时，writer 依赖 stage1 全部结果 → fan-in
    stage1, edges = [], []
    n = {w: 1 for w in hits}
    for w in hits:
        if w == "writer":
            continue
        node = _build_node(w, _task_prompt(q, w, is_single=False), [], n[w])
        stage1.append(node)
        edges.append(["supervisor", node["node_id"], "dispatch"])

    if "writer" in hits:
        wri = _build_node("writer", _task_prompt(q, "writer", is_single=False),
                          [nd["node_id"] for nd in stage1], 1)
        stages = [stage1, [wri]]
        for nd in stage1:
            edges.append([nd["node_id"], "wri_1", "dependency"])
        edges.append(["wri_1", "supervisor", "return"])
        aggregate = "writer"
    else:
        stages = [stage1]
        for nd in stage1:
            edges.append([nd["node_id"], "supervisor", "return"])
        aggregate = "supervisor"

    labels = "、".join(workers_mod.WORKERS[w]["label"] for w in hits)
    stage1_note = (f"并行 fan-out（{len(stage1)} 节点）" if len(stage1) > 1
                   else "仅 1 节点（无可并行分支，纯依赖链）")
    note = (f"命中 {labels} 关键词 → stage1 {stage1_note}"
            + (f"，stage2 写手依赖 stage1 全部成果（fan-in）" if "writer" in hits
               else "，supervisor 聚合 fan-in"))
    return {"plan_id": plan_id, "task_type": "dag", "search_mode": search_mode,
            "stages": stages, "edges": edges, "aggregate": aggregate,
            "route_note": note}


if __name__ == "__main__":
    # 路由自测：无需 LLM，直接验证四条路径的图结构
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cases = [
        "你好",                                                    # direct
        "今天天气怎么样",                                          # direct_llm
        "调研一下中国扫地机器人行业竞争格局",                      # single
        "帮我调研一下中国咖啡市场现状，算一算近三年市场规模（2021年3817亿元、2022年4856亿元、"
        "2023年6188亿元）的年均增速，再写一篇 800 字左右的公众号推文，面向想开店创业的人",  # dag 3 worker
        "写一篇新能源汽车行业科普推文，先调研行业现状",            # dag 依赖链
    ]
    for q in cases:
        p = route(q)
        nodes = [n["node_id"] for st in p["stages"] for n in st]
        print(f"\nQ: {q[:30]}...\n  类型={p['task_type']:<6} 节点={nodes} "
              f"聚合={p['aggregate']} 搜索={p.get('search_mode','-')}")
        print(f"  说明: {p['route_note']}")
        if p.get("edges"):
            print(f"  边: {[(a, b) for a, b, _ in p['edges']]}")
