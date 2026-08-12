"""
代码审查主 Agent + 并行 Subagent 编排

教学重点：
  1. 主审查 agent 是 ReAct 循环，有 4 个工具：
     - read_file / search_code / list_files：直接分析代码（简单 review 直接用）
     - dispatch_reviewers：派发多个子审查员并行审查（多维度深度 review）
     主 agent 根据 review 范围自行决定——不是固定拓扑，是 LLM 自主路由

  2. 并行优势凸显：dispatch_reviewers 一次派发 N 个维度审查员，
     ThreadPoolExecutor 并行跑，wall-clock ≈ max(单维度时长)，
     而非 sum——这就是 subagent 并行的核心价值

  3. 每个子审查员也是 ReAct 循环（read_file + search_code + list_files），
     trace 全程捕获存入 shared_state，供可视化「点节点看 ReAct 过程」

架构对应 PPT 6.3 的 Orchestrator-Workers 拓扑（动态：主 agent 决定派几个维度）。

对比市场调研项目：
  - 市场调研：工具=web_search，维度=市场侧面（销量/竞争/政策）
  - 代码审查：工具=read_file/search_code，维度=审查维度（安全/性能/风格/逻辑/架构）
  - 相同：都是 Orchestrator-Workers + ThreadPool 并行 + SSE 流式可视化
"""

import os
import time
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from react_loop import ReActLoop
from file_tools import read_file, search_code, list_files

logger = logging.getLogger(__name__)

# ── 审查维度定义（dispatch 时可选用的维度）─────────────────────────────────
REVIEW_DIMENSIONS = {
    "security": {
        "name": "安全审查",
        "focus": (
            "审查代码中的安全漏洞：SQL 注入、XSS、命令注入、路径遍历、"
            "硬编码密钥/密码、不安全反序列化、权限绕过、敏感信息泄露、"
            "不安全的加密算法（MD5/SHA1 用于密码）、缺少输入验证等。"
            "重点关注任何直接接收用户输入并传给敏感操作的代码。"
        ),
        "patterns": [
            "eval(", "exec(", "os.system", "subprocess", "shell=True",
            "password", "secret", "api_key", "token", "PRIVATE_KEY",
            "hashlib.md5", "hashlib.sha1", "cryptography",
            "raw SQL", "execute(", "cursor.execute",
            "input(", "request.", "getenv",
        ],
    },
    "performance": {
        "name": "性能审查",
        "focus": (
            "审查代码性能瓶颈：N+1 查询、嵌套循环复杂度、不必要的内存分配、"
            "阻塞 I/O、缺少缓存、大对象拷贝、字符串拼接滥用、"
            "数据库查询未加索引提示、重复计算、算法复杂度问题等。"
        ),
        "patterns": [
            "for.*for", "while.*while",
            "readlines(", ".load(", ".read(",
            "+=", "strcat", "StringBuilder",
            "sleep(", "time.sleep",
            "SELECT.*FROM.*WHERE", "JOIN",
        ],
    },
    "code_style": {
        "name": "代码风格审查",
        "focus": (
            "审查代码风格与可维护性：命名规范（变量/函数/类）、函数长度（>50行警惕）、"
            "文件组织、注释质量、魔法数字、重复代码(DRY)、"
            "深层嵌套（>3层）、参数过多（>5个）、单一职责违反、"
            "import 组织、类型注解缺失等。"
        ),
        "patterns": [
            "def ", "class ", "import ",
            "TODO", "FIXME", "HACK", "XXX",
            "pass", "# ",
        ],
    },
    "logic": {
        "name": "逻辑/错误审查",
        "focus": (
            "审查代码逻辑和潜在 bug：空值/None 处理缺失、边界条件（空列表/零值）、"
            "异常处理不当（裸 except/吞异常）、竞态条件、资源泄漏（未关闭文件/连接）、"
            "类型错误、逻辑反转、off-by-one 错误、除法零检查、"
            "并发安全问题等。"
        ),
        "patterns": [
            "except:", "except Exception",
            ".get(", "None", "null", "undefined",
            "if not", "if.*is None",
            "try:", "finally:",
            "open(", ".close()",
            "len(", "range(",
        ],
    },
    "architecture": {
        "name": "架构审查",
        "focus": (
            "审查架构与设计：模块耦合度、循环依赖、接口设计一致性、"
            "分层架构遵循情况、设计模式滥用/缺失、依赖方向是否正确（依赖倒置）、"
            "配置硬编码、扩展点设计、测试覆盖率迹象、"
            "SOLID 原则违背、模块职责过重（God Class/Module）。"
        ),
        "patterns": [
            "import ", "from ",
            "class ", "def __init__",
            "config", "settings", "constants",
            "TODO", "deprecated",
        ],
    },
}


def _dispatch_reviewers(action_input: str, shared_state: dict = None,
                        on_subagent_step: Callable = None,
                        on_subagent_done: Callable = None,
                        on_dispatch: Callable = None,
                        serial: bool = False) -> str:
    """dispatch_reviewers 工具实现。

    action_input: "维度1 | 维度2 | ..."（管道分隔），或 "all" 派发全部 5 个维度。
    支持的维度名: security, performance, code_style, logic, architecture（支持中英文）

    派发 N 个 subagent 并行审查，收齐返回汇总文本。

    serial=True 时改成串行执行（eval A/B 对比用）。
    """
    raw_inputs = [s.strip() for s in action_input.split("|") if s.strip()]

    # ── 解析维度名（支持中文、英文、缩写）──────────────────────────────
    DIM_MAP = {
        "security": "security", "安全": "security", "安全审查": "security",
        "performance": "performance", "性能": "performance", "性能审查": "performance",
        "code_style": "code_style", "风格": "code_style", "代码风格": "code_style",
        "logic": "logic", "逻辑": "logic", "bug": "logic", "错误": "logic",
        "architecture": "architecture", "架构": "architecture", "设计": "architecture",
    }

    dimension_keys = []
    if len(raw_inputs) == 1 and raw_inputs[0].lower() == "all":
        dimension_keys = list(REVIEW_DIMENSIONS.keys())
    else:
        for ri in raw_inputs:
            key = DIM_MAP.get(ri.lower().replace("审查", ""))
            if key is None:
                # 模糊匹配
                for dk in REVIEW_DIMENSIONS:
                    if dk.startswith(ri.lower()[:4]):
                        key = dk
                        break
            if key and key not in dimension_keys:
                dimension_keys.append(key)

    if not dimension_keys:
        return (f"未识别的审查维度: {action_input}。"
                f"可选: {', '.join(REVIEW_DIMENSIONS.keys())} 或 'all'")

    shared_state = shared_state if shared_state is not None else {}
    shared_state.setdefault("subagents", {})

    # ── 构造 (sid, subagent, dimension_key) 三元组 ─────────────────────
    defs = []
    for dk in dimension_keys:
        dim = REVIEW_DIMENSIONS[dk]
        sid = f"sub_{uuid.uuid4().hex[:6]}"
        sub = ReActLoop(
            agent_name=sid,
            tools={
                "read_file": (read_file,
                              "读取文件。参数 JSON: {\"path\":\"相对路径\"[,\"start\":行号,\"end\":行号]}"),
                "search_code": (search_code,
                                "搜索代码模式。参数 JSON: {\"pattern\":\"模式\"[,\"glob\":\"*.py\"]}"),
                "list_files": (list_files,
                               "列出目录。参数 JSON: {\"dir\":\"子目录\"} 或不传参"),
            },
            max_steps=5,
            model_tag="deepseek-chat(子)",
            system_prompt=SUB_REVIEWER_SYSTEM.format(
                dimension=dim["name"],
                focus=dim["focus"],
            ),
        )
        defs.append((sid, sub, dk))

    # ── 记录派发（拓扑可视化用）─────────────────────────────────────────
    dispatch_info = {
        "subtopics": [REVIEW_DIMENSIONS[dk]["name"] for dk in dimension_keys],
        "subagent_ids": [sid for sid, _, _ in defs],
    }
    shared_state.setdefault("dispatches", []).append(dispatch_info)
    if on_dispatch:
        on_dispatch(dispatch_info)

    t0 = time.time()
    results = {}

    # ── 执行：serial=False 并行(ThreadPool) / serial=True 串行(for 循环) ──
    def _run_one(sid=sid, sub=sub, dk=dk):
        dim = REVIEW_DIMENSIONS[dk]
        question = (
            f"请审查这个项目的「{dim['name']}」维度。\n\n"
            f"审查重点：{dim['focus']}\n\n"
            f"【审查步骤】\n"
            f"1. 先用 list_files 了解项目结构\n"
            f"2. 用 search_code 搜索可疑模式\n"
            f"3. 用 read_file 仔细阅读可疑代码\n"
            f"4. 给出结构化的审查结论（每个发现带：文件名+行号、严重级别、问题描述、修复建议）\n\n"
            f"严重级别：🔴高危 / 🟡中危 / 🟢低危 / 💡建议"
        )
        return sid, sub.run(question, on_step=(
            lambda step, sid=sid: on_subagent_step(sid, step)
            if on_subagent_step else None))

    if serial:
        for sid, sub, dk in defs:
            sid, res = _run_one(sid, sub, dk)
            results[sid] = (dk, res)
            shared_state["subagents"][sid] = {
                "subtopic": REVIEW_DIMENSIONS[dk]["name"],
                "trace": res["trace"],
                "duration": res["duration"],
                "final_answer": res["final_answer"],
            }
            if on_subagent_done:
                on_subagent_done(sid, res["duration"], REVIEW_DIMENSIONS[dk]["name"])
    else:
        # 并行（凸显 subagent 并行优势的核心）
        with ThreadPoolExecutor(max_workers=len(defs)) as pool:
            futs = {pool.submit(_run_one, sid, sub, dk): sid
                    for sid, sub, dk in defs}
            for fut in as_completed(futs):
                sid, res = fut.result()
                dk = next(d for s, _, d in defs if s == sid)
                results[sid] = (dk, res)
                shared_state["subagents"][sid] = {
                    "subtopic": REVIEW_DIMENSIONS[dk]["name"],
                    "trace": res["trace"],
                    "duration": res["duration"],
                    "final_answer": res["final_answer"],
                }
                if on_subagent_done:
                    on_subagent_done(sid, res["duration"],
                                     REVIEW_DIMENSIONS[dk]["name"])

    wall = round(time.time() - t0, 2)
    serial_sum = round(sum(r["duration"] for _, r in results.values()), 2)
    shared_state.setdefault("parallel_stats", []).append({
        "n_subagents": len(defs),
        "wall_clock": wall,
        "serial_sum": serial_sum,
        "speedup": round(serial_sum / wall, 2) if wall else 0,
    })

    # ── 汇总文本（喂回主 agent 当 Observation）────────────────────────
    parts = []
    for sid, (dk, r) in results.items():
        dim_name = REVIEW_DIMENSIONS[dk]["name"]
        parts.append(
            f"【{dim_name}】(用时 {r['duration']}s)\n{r['final_answer'][:600]}"
        )
    stats = shared_state["parallel_stats"][-1]
    return (
        f"并行审查完成：{len(defs)} 个维度审查员，wall-clock {wall}s "
        f"(串行需 {serial_sum}s，加速 {stats['speedup']}×)\n\n" +
        "\n\n".join(parts)
    )


# ── 主审查 Agent 系统提示 ─────────────────────────────────────────────────

MAIN_SYSTEM = """你是资深代码审查专家（Architect-level Code Reviewer）。你有 4 个工具：

- read_file：读取文件（参数 JSON: {"path":"路径"[,"start":行号,"end":行号]}）
- search_code：搜索代码模式（参数 JSON: {"pattern":"模式"[,"glob":"*.py"]}）
- list_files：列出目录结构（参数 JSON: {"dir":"子目录"} 或空参）
- dispatch_reviewers：派发多个维度审查员并行审查

【关键决策原则】
- 只要审查范围涉及「多文件或整个项目」，必须用 dispatch_reviewers 派发并行审查。
  默认派发全部 5 个维度：security | performance | code_style | logic | architecture
  如果用户只关注特定维度，只派那些维度即可。
  示例 Action Input: all  或  security | performance | logic

- 只有单一文件快速检查才直接用 read_file/search_code，不派发子审查员。

- 拿到各维度审查结果后，综合成一份结构化的代码审查报告。

【报告格式要求】
审查报告需包含：
1. 📊 审查概览（审查范围、文件数、问题总数、严重分布）
2. 🔍 各维度发现（按严重级别分组：🔴高危 → 🟡中危 → 🟢低危 → 💡建议）
3. 📋 修复优先级排序（最紧急的排最前）
4. 💬 总结与改进方向（整体评价、架构建议、技术债务）

每个发现需标注：文件名+行号、严重级别、问题描述、修复建议。

【示例】
Question: 请审查这个项目的代码质量
Thought: 这是整个项目的全面审查，涉及多个维度（安全、性能、风格、逻辑、架构），
         必须派发子审查员并行处理，不能自己串行分析每个文件
Action: dispatch_reviewers
Action Input: all
Observation: 并行审查完成：5 个维度审查员，wall-clock 45s...
Thought: 已收齐全部五个维度的审查结果，综合成结构化报告
Final Answer: （分维度报告，带严重级别和修复建议）"""

# ── 子审查员系统提示模板 ──────────────────────────────────────────────────

SUB_REVIEWER_SYSTEM = """你是代码专项审查员，专攻「{dimension}」维度。

审查重点：{focus}

可用工具：
{{tools_desc}}

按如下格式严格输出（每轮一次 Thought/Action/Action Input）：
Thought: 你的推理，分析下一步查什么
Action: 工具名
Action Input: 工具参数

工具执行后会得到 Observation。多轮调用直到能给出完整审查结论，最后用：
Thought: 我已收集足够信息
Final Answer: 审查结论

【输出格式】
每个发现用一行，格式：
- {严重级别} [文件:行号] 问题描述 → 修复建议：具体方案

严重级别：🔴高危 / 🟡中危 / 🟢低危 / 💡建议

规则：
- 先 list_files 了解结构，再 search_code 定位，最后 read_file 确认
- 每个发现必须给出具体行号（不能说"多处"或"一些地方"）
- 没有发现问题也要说明原因（不是"无问题"三个字）
- 最多 5 轮工具调用"""


# ── 主入口 ─────────────────────────────────────────────────────────────────

def run_review(question: str, on_main_step: Callable = None,
               on_subagent_step: Callable = None,
               on_subagent_done: Callable = None,
               on_dispatch: Callable = None,
               serial: bool = False) -> dict:
    """执行一次代码审查。返回 {final_answer, main_trace, subagents, parallel_stats}。

    参数：
      question: 审查问题/范围描述
      serial: True 时 subagent 串行执行（eval A/B 对比基线）
    """
    shared_state = {"subagents": {}, "dispatches": [], "parallel_stats": []}

    def dispatch_tool(action_input, shared_state=None):
        info = shared_state or {}
        return _dispatch_reviewers(
            action_input, shared_state=info,
            on_subagent_step=on_subagent_step,
            on_subagent_done=on_subagent_done,
            on_dispatch=on_dispatch,
            serial=serial,
        )

    main = ReActLoop(
        agent_name="main",
        tools={
            "read_file": (read_file,
                          "读取文件。参数 JSON: {\"path\":\"路径\"[,\"start\":行号,\"end\":行号]}"),
            "search_code": (search_code,
                            "搜索代码模式。参数 JSON: {\"pattern\":\"模式\"[,\"glob\":\"*.py\"]}"),
            "list_files": (list_files,
                           "列出目录结构。参数 JSON: {\"dir\":\"子目录\"} 或空参"),
            "dispatch_reviewers": (dispatch_tool,
                                   "派发多维度审查员并行审查。参数: 维度名(管道分隔)或 'all'"),
        },
        max_steps=8,
        model_tag="deepseek-chat(主)",
        system_prompt=MAIN_SYSTEM,
    )

    result = main.run(question, on_step=on_main_step,
                      shared_state=shared_state)
    return {
        "final_answer": result["final_answer"],
        "main_trace": result["trace"],
        "subagents": shared_state["subagents"],
        "parallel_stats": shared_state["parallel_stats"],
        "dispatches": shared_state["dispatches"],
    }


# ── 自测（审查本项目自身的代码质量）────────────────────────────────────────
if __name__ == "__main__":
    import logging as _l
    _l.basicConfig(level=_l.WARNING)
    os.environ.setdefault("PROJECT_ROOT",
                          os.path.join(os.path.dirname(__file__), ".."))

    q = "请审查这个代码审查系统的项目代码：检查安全性、代码风格、逻辑错误"
    print(f"审查范围: {q}")
    r = run_review(q)
    print(f"\n{'=' * 60}")
    print(f"主 agent 动作: {[s['action'] for s in r['main_trace']]}")
    print(f"派发次数: {len(r['dispatches'])} | subagent 数: {len(r['subagents'])}")
    print(f"并行统计: {r['parallel_stats']}")
    print(f"\n报告（前 500 字）:\n{r['final_answer'][:500]}")
