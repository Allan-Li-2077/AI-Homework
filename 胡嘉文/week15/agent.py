"""
可下发 subagent 的并行 Agent 演示（Orchestrator → Subagents 模式）

教学重点：
  1. 主 Agent（orchestrator）把复杂任务拆解为多个独立子任务
  2. 每个子任务下发给一个 subagent，用 ThreadPoolExecutor 并行执行
  3. 所有 subagent 结果收集完毕后，由主 Agent 汇总成最终答案
  4. --mock 模式无需 API Key：用随机延迟 + 固定答案模拟并行，便于演示
  5. 输出墙钟耗时，并与「串行估算耗时」对比，直观展示并行收益

使用方式：
  python agent.py                        # 真实 LLM（需 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY）
  python agent.py --mock                 # 模拟模式，无需任何 Key
  python agent.py --question "对比北京和上海的生活成本" --mock
  python agent.py --subagents 4          # 指定拆解子任务数量

环境变量：
  DEEPSEEK_API_KEY      使用 DeepSeek（默认）
  DASHSCOPE_API_KEY     使用阿里云 DashScope（LLM_PROVIDER=qwen 时）
  LLM_PROVIDER          deepseek | qwen，切换供应商
  AGENT_MODEL           覆盖默认模型（deepseek-v4-flash / qwen-max）

依赖：
  pip install openai
"""

import os
import json
import time
import random
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# ── ANSI 颜色 ─────────────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
CYAN    = "\033[36m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
MAGENTA = "\033[35m"
DIM     = "\033[2m"

# 每个 subagent 一个颜色，便于看出「并行交错」执行
SUB_COLORS = [
    "\033[34m",  # 蓝
    "\033[36m",  # 青
    "\033[32m",  # 绿
    "\033[33m",  # 黄
    "\033[35m",  # 紫
    "\033[31m",  # 红
    "\033[96m",  # 亮青
    "\033[93m",  # 亮黄
]

DEFAULT_QUESTION = "对比 DeepSeek、Qwen、GPT、Claude 四款大模型的特点、优势与适用场景"


# ── 模型配置（沿用 week12/week13 的切换方式）─────────────────────────────────

def get_chat_client():
    """返回 (client, model)。支持 deepseek / qwen 两套供应商。"""
    provider = os.getenv("LLM_PROVIDER", "deepseek").lower()
    if provider == "qwen":
        client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        model = os.getenv("AGENT_MODEL", "qwen-max")
    else:
        client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )
        model = os.getenv("AGENT_MODEL", "deepseek-v4-flash")
    return client, model


# ── 三个 Prompt 模板 ──────────────────────────────────────────────────────────

DECOMPOSE_PROMPT = """你是任务编排 Agent（Orchestrator）。请把下面的复杂任务拆解成 {n} 个互相独立的子任务，每个子任务可以交给一个 subagent 并行完成。

要求：
- 子任务之间必须完全独立，互不依赖，可并行执行
- 每个子任务给出简洁的任务描述，让 subagent 能独立作答
- 只输出一个严格的 JSON 数组，不要输出任何其他文字或代码块标记

格式：
[{{"id": 1, "title": "子任务1标题", "task": "子任务1的具体描述"}}, ...]

待拆解的任务：
{question}
"""

SUBAGENT_PROMPT = """你是一名 Subagent（子代理），隶属于一个更大的任务编排系统。你只负责完成下面这一项子任务，不要涉及其他内容。请直接给出简洁、专业、可读的结论。

子任务：{task}
"""

SYNTHESIS_PROMPT = """你是任务编排 Agent（Orchestrator）。以下是多个 subagent 并行完成后返回的结果，以及最初的原始问题。请把这些零散结果汇总、去重、整合，生成一份结构清晰、有逻辑的最终综合答案。

原始问题：
{question}

subagent 返回结果：
{results}
"""


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _chat(client, model, messages, temperature=0.7):
    """单次非流式 LLM 调用。"""
    resp = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature
    )
    return resp.choices[0].message.content or ""


def _print_sub(sub_idx, sub_color, text):
    print(f"  {sub_color}[subagent #{sub_idx}]{RESET} {text}")


# ── 1. 拆解 ──────────────────────────────────────────────────────────────────

_LEADING_VERB = r"^(对比|比较|分析|研究|评估|总结|介绍)"


def _mock_decompose(question, n):
    """
    mock 模式下的确定性拆解：尽量把「并列项」拆成独立子任务。
    1. 去掉开头动词（对比/比较/分析…）
    2. 遇到 "四款/几类…" 等计数列举词，列表在此截止（去掉共享尾缀）
    3. 按 "、/，/和/与" 切分；最后一个子项若带 "…的…" 共享描述，去尾缀
    切不出来时回退为 n 个泛化子任务。
    """
    import re
    text = re.sub(_LEADING_VERB, "", question).strip()

    parts = [p.strip() for p in re.split(r"[、，,]", text) if p.strip()]
    # 2) 计数列举词截止（如 "DeepSeek、Qwen、GPT、Claude 四款…" → 取计数词之前）
    count_m = re.search(r"[一二三四五六七八九十几多]\s*[款个类项种]", text)
    if count_m and len(parts) >= 2:
        head = text[:count_m.start()]
        items = [p.strip() for p in re.split(r"[、，,]", head) if p.strip()]
        if len(items) >= 2:
            parts = items

    # 3) 每个 part 内按 和/与 再切，并去掉最后一项的共享尾缀
    flat = []
    for p in parts:
        flat += [x.strip() for x in re.split(r"[和与]", p) if x.strip()]
    if len(flat) >= 2:
        last = flat[-1]
        pos = None
        for marker in ("等", "的"):
            idx = last.find(marker)
            if idx > 0 and (pos is None or idx < pos):
                pos = idx
        if pos:
            flat[-1] = last[:pos].strip()
    parts = [p for p in flat if p]

    if len(parts) < 2:
        parts = [f"第 {i + 1} 个独立方面" for i in range(n)]
    return [
        {
            "id": i + 1,
            "title": p,
            "task": f"针对主问题「{question}」，从「{p}」这一独立方面给出要点分析与简洁结论。",
        }
        for i, p in enumerate(parts[:n])
    ]


def decompose(question, n, client, model, mock=False):
    """
    主 Agent 把问题拆解为 n 个子任务。
    返回子任务列表；mock 模式走确定性切分；真实模式解析失败时回退为单子任务。
    """
    print(f"\n{CYAN}── ① 拆解任务 ──{RESET}")

    if mock:
        tasks = _mock_decompose(question, n)
        print(f"  {DIM}[mock] 按并列项切分出子任务{RESET}")
    else:
        prompt = DECOMPOSE_PROMPT.format(n=n, question=question)
        raw = _chat(client, model, [
            {"role": "system", "content": "你是一个任务拆解助手。"},
            {"role": "user", "content": prompt},
        ], temperature=0.3)
        tasks = _parse_subtasks(raw)
        if not tasks:
            print(f"  {YELLOW}[警告] 拆解输出不是合法 JSON，回退为单子任务：{raw[:80]}…{RESET}")
            tasks = [{"id": 1, "title": "完整任务", "task": question}]

    print(f"  {GREEN}✓ 拆解出 {len(tasks)} 个子任务：{RESET}")
    for t in tasks:
        print(f"    {DIM}· [{t['id']}] {t.get('title', '')}{RESET}")
    return tasks


def _parse_subtasks(raw):
    """从模型输出中提取 JSON 数组，容忍多余的 ```json 包裹。"""
    if not raw:
        return []
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    # 截取第一个 '[' 到最后一个 ']'
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text[start:end + 1])
        if not isinstance(data, list):
            return []
        return [d for d in data if isinstance(d, dict) and d.get("task")]
    except json.JSONDecodeError:
        return []


# ── 2. subagent 执行（真实 LLM）──────────────────────────────────────────────

def run_subagent(task, client, model):
    """单个 subagent：只携带自己的子任务，独立作答。"""
    prompt = SUBAGENT_PROMPT.format(task=task["task"])
    return _chat(client, model, [
        {"role": "system", "content": "你是专业、简洁的子任务执行者。"},
        {"role": "user", "content": prompt},
    ])


def mock_run_subagent(task):
    """
    mock 模式：随机延迟 + 固定模板答案，演示并行效果。
    返回答案文本；耗时由调用方计时。
    """
    time.sleep(random.uniform(0.5, 2.0))
    return (
        f"[模拟结果] 子任务「{task.get('title', task['task'][:20])}」已处理完成。\n"
        f"要点：该子任务与其余子任务相互独立，可在不同线程并行执行。"
    )


# ── 3. 并行下发 ──────────────────────────────────────────────────────────────

def dispatch_parallel(tasks, client, model, mock=False):
    """
    用 ThreadPoolExecutor 把每个子任务下发给一个 subagent，并行执行。
    按完成顺序打印进度（as_completed），体现并行交错。
    返回 (结果列表, 实际墙钟耗时, 每个 subagent 耗时列表)。
    """
    n = len(tasks)
    print(f"\n{CYAN}── ② 并行下发 {n} 个 subagent ──{RESET}")
    print(f"  {DIM}（ThreadPoolExecutor 并行执行，进度按完成顺序打印）{RESET}\n")

    results = [None] * n
    durations = [0.0] * n          # 每个 subagent 的实际耗时，用于串行估算
    start = time.time()
    done = 0

    def _worker(idx, task):
        """单个 subagent 的工作单元（在线程池中执行）。"""
        no = idx + 1
        color = SUB_COLORS[idx % len(SUB_COLORS)]
        t0 = time.time()
        if mock:
            text = mock_run_subagent(task)
            _print_sub(no, color, f"{BOLD}完成{RESET} 工作 {time.time() - t0:.1f}s")
        else:
            _print_sub(no, color, f"{DIM}工作中…{RESET}")
            text = run_subagent(task, client, model)
            _print_sub(no, color, f"{BOLD}完成{RESET}")
        return text, time.time() - t0

    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = {pool.submit(_worker, idx, t): idx for idx, t in enumerate(tasks)}
        for fut in as_completed(futures):
            idx = futures[fut]
            no = idx + 1
            try:
                text, dur = fut.result()
            except Exception as e:
                # 单个 subagent 失败不影响整体流程，记入失败结果
                color = SUB_COLORS[idx % len(SUB_COLORS)]
                _print_sub(no, color, f"{YELLOW}失败：{e}{RESET}")
                text, dur = f"[该 subagent 执行失败：{e}]", 0.0
            results[idx], durations[idx] = text, dur
            done += 1
            print(f"  {DIM}已收集 {done}/{n} 份子结果{RESET}\n")

    elapsed = time.time() - start
    return results, elapsed, durations


# ── 4. 汇总 ──────────────────────────────────────────────────────────────────

def synthesize(question, results, client, model):
    """主 Agent 汇总所有 subagent 结果，生成最终综合答案。"""
    print(f"\n{CYAN}── ③ 汇总最终答案 ──{RESET}")
    blocks = "\n\n".join(
        f"【subagent #{i + 1}】\n{r}" for i, r in enumerate(results)
    )
    prompt = SYNTHESIS_PROMPT.format(question=question, results=blocks)
    return _chat(client, model, [
        {"role": "system", "content": "你是汇总整合专家。"},
        {"role": "user", "content": prompt},
    ])


# ── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="可下发 subagent 的并行 Agent Demo")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="要拆解的复杂任务")
    parser.add_argument("--subagents", type=int, default=4, help="拆解的子任务数量（默认 4）")
    parser.add_argument("--mock", action="store_true", help="mock 模式：无需 API Key，模拟并行")
    args = parser.parse_args()

    print(f"\n{BOLD}{'=' * 62}{RESET}")
    print(f"{BOLD}  🤖 可下发 subagent 的并行 Agent Demo{RESET}")
    print(f"  主问题：{args.question}")
    print(f"{BOLD}{'=' * 62}{RESET}")

    # 未加 --mock 且没配 Key 时，自动回落 mock 模式
    mock = args.mock
    if not mock:
        key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if not key:
            print(f"\n{YELLOW}[提示] 未检测到 API Key，自动使用 --mock 模式。"
                  f"（配置 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY 后走真实 LLM）{RESET}")
            mock = True

    client, model = None, None
    if not mock:
        client, model = get_chat_client()
        print(f"  模型：{CYAN}{model}{RESET}  "
              f"{DIM}（LLM_PROVIDER={os.getenv('LLM_PROVIDER', 'deepseek')}）{RESET}")

    # ① 拆解
    tasks = decompose(args.question, args.subagents, client, model, mock=mock)

    # ② 并行下发 subagent
    results, parallel_elapsed, durations = dispatch_parallel(
        tasks, client, model, mock=mock
    )

    # 并行/串行耗时对比：串行 ≈ 各 subagent 实际耗时之和（mock 精确，真实模式为实测参考）
    serial_est = sum(durations)
    print(f"\n  {MAGENTA}⏱ 墙钟耗时：{parallel_elapsed:.2f}s"
          f"{DIM}  （{len(tasks)} 个 subagent 并行，估算串行约 {serial_est:.2f}s，"
          f"加速约 {serial_est / parallel_elapsed:.1f}×）{RESET}")

    # ③ 汇总
    if mock:
        # mock 模式不调 LLM，直接拼一份演示用汇总
        final = "\n".join(
            f"### subagent #{i + 1}：{t.get('title', '')}\n{r}"
            for i, (t, r) in enumerate(zip(tasks, results))
        )
    else:
        final = synthesize(args.question, results, client, model)

    print(f"\n{GREEN}{'=' * 62}{RESET}")
    print(f"{GREEN}  📋 最终汇总答案{RESET}")
    print(f"{GREEN}{'=' * 62}{RESET}")
    print(final)
    print()


if __name__ == "__main__":
    main()
