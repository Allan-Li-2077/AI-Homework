"""
可下发 Sub-Agent 的 Orchestrator（编排器）

核心思想：
  主 agent（编排器）自身不直接干活，而是通过 dispatch_agent 工具把任务
  委派给专门的 sub-agent。每个 sub-agent 拥有：
    - 独立上下文（fresh messages）：中间的思考/工具调用/观测都留在自己
      的对话里，不污染主 agent 的上下文，主 agent 只收到最终答案。
    - 专属 system prompt：角色专精（如只读研究员 explore、通用助手 general）。
    - 受限工具集：最小权限，explore 不能 calculator，更不能写文件。
  sub-agent 跑完自己的 function-calling 循环后，只把最终答案回传给主 agent。

为什么需要 sub-agent：
  - 省 token：sub-agent 的中间过程不进入主 agent 上下文，避免被大量观测撑爆。
  - 可并行：主 agent 一次可 dispatch 多个 sub-agent（本实现用线程池并发）。
  - 可专精：不同 subagent_type 有不同 prompt 与工具，能力边界清晰。
  - 可隔离：sub-agent 出错只影响该子任务，主 agent 据此重试或换策略。

流程（主 agent 的 Function Calling 循环）：
  1. system prompt = 编排指令 + 可用 sub-agent 目录（name + description）
  2. 暴露 dispatch_agent(task, subagent_type, focus_path?) 工具
  3. 用户提问 → 主 agent 判断要不要委派
       ├─ 委派 → dispatch_agent → 启动 sub-agent 独立循环 → 回传最终答案
       └─ 不委派 → 直接回答（通识问题）
  4. 无 API Key 时走 mock：sub-agent 用规则引擎真正执行任务（真干活）

使用：
  python orchestrator.py list                               # 列出 sub-agent 类型
  python orchestrator.py run "workspace 里有哪些文件？分别讲什么"   # 有 Key 调 LLM，无 Key 走 mock
  python orchestrator.py run "..." --mock                   # 强制 mock
  python orchestrator.py demo                               # 跑一个内置示例
  python orchestrator.py agents                             # 查看 sub-agent 配置

环境变量：
  DEEPSEEK_API_KEY / DASHSCOPE_API_KEY   有则调真实 LLM，无则自动 mock
  AGENT_MODEL                             默认 deepseek-chat / qwen-max
"""

import os
import re
import sys
import json
import time
import argparse
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from tools import TOOLS, TOOL_SCHEMAS, schemas_for, call_tool

COLORS = {
    "name":    "\033[1;36m",
    "desc":    "\033[2;37m",
    "tool":    "\033[33m",
    "sub":     "\033[1;34m",
    "subtool": "\033[36m",
    "obs":     "\033[2;32m",
    "answer":  "\033[35m",
    "warn":    "\033[33m",
    "err":     "\033[31m",
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "dim":     "\033[2m",
}


def _c(color: str, text: str) -> str:
    return f"{COLORS[color]}{text}{COLORS['reset']}"


# ── Sub-Agent 配置 ──────────────────────────────────────────────────────────

@dataclass
class SubAgentConfig:
    name: str
    description: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{_c('name', self.name)}  "
            f"{_c('desc', self.description[:64])}  "
            f"[tools: {', '.join(self.tools) or '（无）'}]"
        )

    def detail(self) -> str:
        return (
            f"{_c('bold', f'SubAgent: {self.name}')}\n"
            f"  描述:   {self.description}\n"
            f"  工具:   {', '.join(self.tools) or '（无）'}\n"
            f"  ── System Prompt ──\n{self.system_prompt.strip()}"
        )


SUBAGENTS: dict[str, SubAgentConfig] = {
    "explore": SubAgentConfig(
        name="explore",
        description="只读的代码/文件研究员。用于探索文件结构、查找内容、理解项目。绝不修改文件。",
        tools=["list_files", "search", "read_file"],
        system_prompt=(
            "你是一个只读的研究助手（explore）。你只能读取，绝不修改任何文件。\n"
            "接到任务后，按以下方式自主探索 workspace：\n"
            "1. 先用 list_files 看目录结构\n"
            "2. 用 search 用关键词/正则定位相关内容\n"
            "3. 用 read_file 精读关键文件\n"
            "4. 每一步都基于观测到的真实内容，不要臆测\n"
            "完成后给出简明、基于事实的结论。"
        ),
    ),
    "general": SubAgentConfig(
        name="general",
        description="通用助手。可读文件和做算术计算，适合需要查找+计算的综合任务。",
        tools=["list_files", "search", "read_file", "calculator"],
        system_prompt=(
            "你是一个通用助手（general）。你可以列目录、搜内容、读文件、做算术计算。\n"
            "自主决定如何用工具完成任务，所有数字运算必须用 calculator 工具，不能心算。\n"
            "完成后给出清晰的最终答案。"
        ),
    ),
}


# ── LLM 客户端 ──────────────────────────────────────────────────────────────

def get_llm_client_and_model(model: str = None):
    """返回 (client, model) 或 (None, None)。无 Key 时返回 None 触发 mock。"""
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        return None, None
    from openai import OpenAI
    if os.getenv("DEEPSEEK_API_KEY"):
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        model = model or os.getenv("AGENT_MODEL", "deepseek-chat")
    else:
        client = OpenAI(api_key=api_key,
                        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        model = model or os.getenv("AGENT_MODEL", "qwen-max")
    return client, model


# ── Sub-Agent 独立循环（真实 LLM） ──────────────────────────────────────────

def run_subagent(config: SubAgentConfig, task: str, model: str = None,
                 max_steps: int = 6, indent: str = "    ") -> str:
    """启动一个 sub-agent，跑自己的 function-calling 循环，返回最终答案。

    关键：messages 在函数内新建（fresh context），主 agent 看不到这里的中间过程。
    """
    client, resolved_model = get_llm_client_and_model(model)
    if client is None:
        return run_subagent_mock(config, task, indent=indent)

    messages = [
        {"role": "system", "content": config.system_prompt},
        {"role": "user", "content": task},
    ]
    tools = schemas_for(config.tools)

    print(f"{indent}{_c('sub', f'▶ SubAgent[{config.name}] 启动')}（模型 {resolved_model}，工具 {config.tools}）")
    print(f"{indent}{_c('dim', f'  task: {task}')}")
    start = time.time()

    for step in range(1, max_steps + 1):
        resp = client.chat.completions.create(
            model=resolved_model, messages=messages,
            tools=tools, tool_choice="auto", temperature=0,
        )
        msg = resp.choices[0].message
        reason = resp.choices[0].finish_reason

        # sub-agent 给出最终答案
        if reason == "stop" or not msg.tool_calls:
            answer = msg.content or "（sub-agent 返回空内容）"
            elapsed = time.time() - start
            print(f"{indent}{_c('sub', f'■ SubAgent[{config.name}] 完成')}（{step} 步，{elapsed:.1f}s）")
            return answer

        # sub-agent 请求调用工具
        messages.append(msg)
        for tc in msg.tool_calls:
            tname = tc.function.name
            try:
                targs = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                targs = {}
            print(f"{indent}{_c('subtool', f'  [sub step {step}] {tname}({json.dumps(targs, ensure_ascii=False)})')}")
            obs = call_tool(tname, targs)
            print(f"{indent}{_c('obs', f'    → {obs[:160]}')}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": obs})

    elapsed = time.time() - start
    print(f"{indent}{_c('warn', f'■ SubAgent[{config.name}] 达到最大步数 {max_steps}（{elapsed:.1f}s）')}")
    return f"（sub-agent[{config.name}] 达到最大步数 {max_steps}，未能给出最终答案）"


# ── Sub-Agent Mock（无 API Key，规则引擎真干活） ────────────────────────────

def run_subagent_mock(config: SubAgentConfig, task: str, indent: str = "    ") -> str:
    """无 Key 时用规则引擎驱动 sub-agent：依据任务关键词真正调用工具。

    目的是让 mock 模式也能 end-to-end 跑通「委派→工具→结论」，而非假装。
    """
    print(f"{indent}{_c('sub', f'▶ SubAgent[{config.name}] 启动')}（mock 规则引擎，工具 {config.tools}）")
    print(f"{indent}{_c('dim', f'  task: {task}')}")
    t = task.lower()
    observations: list[str] = []
    step = 0

    def _step(name, args):
        nonlocal step
        step += 1
        print(f"{indent}{_c('subtool', f'  [sub step {step}] {name}({json.dumps(args, ensure_ascii=False)})')}")
        obs = call_tool(name, args)
        observations.append(f"{name}({args}) -> {obs}")
        print(f"{indent}{_c('obs', f'    → {obs[:160]}')}")
        return obs

    # 列目录类任务
    if any(k in t for k in ("列出", "有哪些文件", "目录", "list", "结构", "什么文件")):
        if "list_files" in config.tools:
            obs = _step("list_files", {"directory": "."})
            # 顺手读一下 README，让结论更有内容
            if "read_file" in config.tools and "readme" in obs.lower():
                _step("read_file", {"path": "README.md"})

    # 搜索/查找类任务
    elif any(k in t for k in ("搜索", "查找", "找", "search", "包含", "提到", "mention")):
        if "search" in config.tools:
            pat = _extract_pattern(task) or "sub-agent|subagent|dispatch"
            _step("search", {"pattern": pat, "path": "."})

    # 读文件类任务
    elif any(k in t for k in ("读取", "查看", "看看", "read", "内容", "讲什么", "是什么")):
        if "read_file" in config.tools:
            fname = _extract_filename(task) or "README.md"
            _step("read_file", {"path": fname})

    # 计算类任务
    elif any(k in t for k in ("计算", "算", "多少", "calcu", "=+", "总和", "合计")):
        if "calculator" in config.tools:
            expr = _extract_expr(task) or "1+1"
            _step("calculator", {"expression": expr})
        else:
            observations.append(f"（{config.name} 没有 calculator 工具，无法计算）")

    # 兜底：至少 list_files 一次，给出结构化结论
    else:
        if "list_files" in config.tools:
            _step("list_files", {"directory": "."})
        if "search" in config.tools:
            _step("search", {"pattern": _extract_pattern(task) or "待办|todo", "path": "."})

    # 综合观测生成「最终答案」
    if not observations:
        answer = f"（mock）[{config.name}] 没有可用工具或未识别任务类型，无法完成。"
    else:
        joined = "\n".join(f"- {o[:200]}" for o in observations)
        answer = (f"【mock sub-agent[{config.name}] 报告】\n"
                  f"任务: {task}\n"
                  f"共执行 {step} 步工具调用，观测如下：\n{joined}\n"
                  f"结论: 已基于上述真实工具观测完成任务（mock 模式未调用 LLM，如需更深入分析请配置 API Key）。")
    print(f"{indent}{_c('sub', f'■ SubAgent[{config.name}] 完成')}（mock，{step} 步）")
    return answer


def _extract_pattern(text: str) -> str:
    m = re.search(r'[\'"“”』]([^\'"”』]+)[\'"“”』]', text)
    return m.group(1) if m else ""


def _extract_filename(text: str) -> str:
    m = re.search(r'([\w\-]+\.md|[\w\-]+\.txt|[\w\-]+\.py)', text, re.IGNORECASE)
    return m.group(1) if m else ""


def _extract_expr(text: str) -> str:
    """从文本中提取算术表达式：必须以数字开头、以数字结尾、且含运算符。"""
    for m in re.finditer(r'\d[\d\s\+\-\*\/\(\)\.\%]*\d', text):
        expr = m.group(0).strip()
        if any(ch in expr for ch in "+-*/"):
            return expr
    return ""


# ── 主 Agent（编排器）工具 ──────────────────────────────────────────────────

def build_orchestrator_system_prompt() -> str:
    """编排器 system prompt：只放 sub-agent 目录（name+desc），不放完整 prompt。"""
    catalog = "\n".join(f"  - {c.name}: {c.description}" for c in SUBAGENTS.values())
    return f"""你是一个任务编排器（Orchestrator）。你自己不直接操作文件或计算，
而是通过 dispatch_agent 工具把子任务委派给专门的 sub-agent 完成。

## 可用 Sub-Agent 目录
{catalog}

## 编排规则
- 通识问题（不需要读文件/计算）你可以直接回答，无需委派。
- 需要探索文件、查找内容、读取数据、计算的任务，必须用 dispatch_agent 委派给合适的 sub-agent。
- 一次可以委派多个 sub-agent（在同一个回复里多次调用 dispatch_agent），它们会并行执行。
- 收到 sub-agent 的最终答案后，综合所有结果给用户一个清晰的回答。
- 给 sub-agent 的 task 要具体、自包含（sub-agent 看不到你和用户的对话）。"""


def build_dispatch_tool() -> list[dict]:
    """dispatch_agent 工具 schema：主 agent 唯一的工具。"""
    return [{
        "type": "function",
        "function": {
            "name": "dispatch_agent",
            "description": "把一个子任务委派给 sub-agent 执行。sub-agent 有独立上下文，跑完后只回传最终答案。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "交给 sub-agent 的具体任务描述，需自包含",
                    },
                    "subagent_type": {
                        "type": "string",
                        "enum": list(SUBAGENTS.keys()),
                        "description": "使用哪种 sub-agent",
                    },
                },
                "required": ["task", "subagent_type"],
            },
        },
    }]


def execute_dispatch(task: str, subagent_type: str, model: str = None) -> str:
    """执行 dispatch_agent：启动对应 sub-agent，返回其最终答案。"""
    config = SUBAGENTS.get(subagent_type)
    if config is None:
        return f"错误：未知的 sub-agent 类型 '{subagent_type}'，可选: {list(SUBAGENTS.keys())}"
    print(_c("tool", f"\n  ┌─ dispatch_agent(subagent_type={subagent_type!r})"))
    answer = run_subagent(config, task, model=model)
    print(_c("tool", f"  └─ dispatch_agent 返回（{len(answer)} 字符）"))
    print(_c("dim", f"     {answer[:160]}"))
    return answer


def execute_dispatch_parallel(dispatches: list[dict], model: str = None) -> dict[str, str]:
    """并行执行多个 dispatch_agent 调用，返回 {call_id: answer}。"""
    if len(dispatches) == 1:
        d = dispatches[0]
        return {d["call_id"]: execute_dispatch(d["task"], d["subagent_type"], model=model)}

    print(_c("tool", f"\n  ╳ 并行委派 {len(dispatches)} 个 sub-agent"))
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(len(dispatches), 4)) as pool:
        futures = {
            pool.submit(execute_dispatch, d["task"], d["subagent_type"], model): d["call_id"]
            for d in dispatches
        }
        for fut in as_completed(futures):
            call_id = futures[fut]
            try:
                results[call_id] = fut.result()
            except Exception as e:
                results[call_id] = f"错误：sub-agent 执行异常: {e}"
    return results


# ── 主 Agent 循环（真实 LLM） ───────────────────────────────────────────────

def run_orchestrator(user_query: str, model: str = None, max_steps: int = 6):
    client, resolved_model = get_llm_client_and_model(model)
    if client is None:
        run_orchestrator_mock(user_query)
        return

    messages = [
        {"role": "system", "content": build_orchestrator_system_prompt()},
        {"role": "user", "content": user_query},
    ]
    tools = build_dispatch_tool()

    print(f"\n{'='*64}")
    print(f"模式:   Orchestrator（真实 LLM）  模型: {resolved_model}")
    print(f"问题:   {user_query}")
    print(f"{'='*64}")
    print(_c("dim", "── 编排器 system prompt（仅 sub-agent 目录）──"))
    print(_c("dim", build_orchestrator_system_prompt()[:400] + " ..."))

    start = time.time()
    dispatched = 0

    for step in range(1, max_steps + 1):
        resp = client.chat.completions.create(
            model=resolved_model, messages=messages,
            tools=tools, tool_choice="auto", temperature=0,
        )
        msg = resp.choices[0].message
        reason = resp.choices[0].finish_reason

        # 编排器给出最终答案
        if reason == "stop" or not msg.tool_calls:
            elapsed = time.time() - start
            print(f"\n{'─'*64}")
            if dispatched:
                print(_c("tool", f"本次共委派 {dispatched} 个 sub-agent"))
            print(_c("answer", f"\n✅ 最终回答:\n{msg.content}"))
            print(f"\n编排器共 {step} 步，耗时 {elapsed:.1f}s")
            return

        # 编排器请求 dispatch_agent
        messages.append(msg)
        dispatches: list[dict] = []
        for tc in msg.tool_calls:
            if tc.function.name != "dispatch_agent":
                print(_c("warn", f"\n[Step {step}] 编排器调用了未知工具: {tc.function.name}"))
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": f"未知工具: {tc.function.name}"})
                continue
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            task = args.get("task", "")
            stype = args.get("subagent_type", "")
            print(_c("tool", f"\n[Step {step}] 编排器调用 dispatch_agent(subagent_type={stype!r})"))
            dispatches.append({"call_id": tc.id, "task": task, "subagent_type": stype})
            dispatched += 1

        answers = execute_dispatch_parallel(dispatches, model=model)
        for call_id, answer in answers.items():
            messages.append({"role": "tool", "tool_call_id": call_id, "content": answer})

    print(_c("warn", f"\n⚠️  编排器已达最大步数 {max_steps}"))


# ── 主 Agent Mock（无 API Key） ─────────────────────────────────────────────

def run_orchestrator_mock(user_query: str):
    """无 Key 时模拟编排器：根据问题特征决定委派哪种 sub-agent。"""
    print(f"\n{'='*64}")
    print(f"模式:   Orchestrator（Mock，无 API Key）")
    print(f"问题:   {user_query}")
    print(f"{'='*64}")
    print(_c("dim", "── 编排器 system prompt（仅 sub-agent 目录）──"))
    print(_c("dim", build_orchestrator_system_prompt()))

    q = user_query.lower()
    needs_calc = any(k in q for k in ("计算", "算", "calcu", "总和", "合计", "等于多少"))
    # 注意「多少」单独不触发计算（可能是「有多少文件」），需配合算术运算符
    has_arith = bool(re.search(r"[\d\s]+\s*[\+\-\*\/x×÷]\s*[\d\s]", q))
    needs_calc = needs_calc or (has_arith and any(k in q for k in ("算", "等于", "多少", "=")))
    needs_explore = any(k in q for k in ("文件", "目录", "搜索", "查找", "读取", "内容", "看看", "找", "讲什么", "是什么", "workspace"))

    # 复合任务：既要探索又要计算 → 拆成两个自包含子任务，并行委派
    if needs_calc and needs_explore:
        explore_task = "探索 workspace 目录，列出有哪些文件并简要说明各自内容"
        calc_expr = _extract_expr(user_query) or "1+1"
        calc_task = f"计算 {calc_expr}"
        print(_c("tool", "\n【模拟】编排器判断：复合任务（探索 + 计算），拆分为两个子任务并行委派"))
        dispatches = [
            {"call_id": "mock-explore", "task": explore_task, "subagent_type": "explore"},
            {"call_id": "mock-calc", "task": calc_task, "subagent_type": "general"},
        ]
        answers = execute_dispatch_parallel(dispatches)
        # 按调用顺序整理
        ordered = [answers[d["call_id"]] for d in dispatches]

    elif needs_calc:
        calc_expr = _extract_expr(user_query) or "1+1"
        dispatches = [{"call_id": "mock-calc", "task": user_query, "subagent_type": "general"}]
        print(_c("tool", "\n【模拟】编排器判断：需要计算，委派给 general sub-agent"))
        ordered = [execute_dispatch(user_query, "general")]

    elif needs_explore:
        dispatches = [{"call_id": "mock-explore", "task": user_query, "subagent_type": "explore"}]
        print(_c("tool", "\n【模拟】编排器判断：需要探索文件，委派给 explore sub-agent"))
        ordered = [execute_dispatch(user_query, "explore")]

    else:
        print(_c("warn", "\n【模拟】编排器判断：通识问题，直接回答，不委派"))
        print(_c("answer", "\n✅ （模拟）编排器直接回答（未委派 sub-agent）"))
        print(_c("warn", "\n⚠️  这是模拟输出。设置 DEEPSEEK_API_KEY / DASHSCOPE_API_KEY 可调用真实 LLM。"))
        return

    print(f"\n{'─'*64}")
    print(_c("answer", f"\n✅ 编排器综合 {len(ordered)} 个 sub-agent 的答案后给出最终回答:"))
    for i, ans in enumerate(ordered, 1):
        print(_c("dim", f"\n--- sub-agent #{i} 报告 ---\n{ans}"))
    print(_c("warn", "\n⚠️  这是模拟输出（sub-agent 用规则引擎真干活，编排器综合步骤为模拟）。"
                       "设置 API Key 可让 LLM 自主决策与综合。"))


# ── CLI ─────────────────────────────────────────────────────────────────────

DEMO_QUERY = "workspace 目录里有哪些文件？分别讲什么？另外帮我算一下 123*45+67 等于多少"


def main():
    parser = argparse.ArgumentParser(
        description="可下发 Sub-Agent 的 Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python orchestrator.py list
  python orchestrator.py agents
  python orchestrator.py run "workspace 里有哪些文件？分别讲什么"
  python orchestrator.py run "搜索哪些文件提到了 sub-agent" --mock
  python orchestrator.py demo                 # 跑内置示例（含并行委派）
        """,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="列出所有 sub-agent 类型")
    sub.add_parser("agents", help="查看 sub-agent 完整配置")

    run_p = sub.add_parser("run", help="编排执行")
    run_p.add_argument("query", help="用户问题")
    run_p.add_argument("--mock", action="store_true", help="强制 mock 模式（不调 LLM）")
    run_p.add_argument("--model", default=None, help="模型名称")
    run_p.add_argument("--max_steps", type=int, default=6)

    sub.add_parser("demo", help="跑内置示例（含并行委派）")

    args = parser.parse_args()

    if args.command is None or args.command == "list":
        print(f"\n已注册 {len(SUBAGENTS)} 个 sub-agent 类型:\n")
        for c in SUBAGENTS.values():
            print(f"  {c.summary()}")
        print()

    elif args.command == "agents":
        for c in SUBAGENTS.values():
            print(c.detail())
            print()

    elif args.command == "run":
        if args.mock:
            run_orchestrator_mock(args.query)
        else:
            run_orchestrator(args.query, model=args.model, max_steps=args.max_steps)

    elif args.command == "demo":
        run_orchestrator(DEMO_QUERY, max_steps=6)


if __name__ == "__main__":
    main()
