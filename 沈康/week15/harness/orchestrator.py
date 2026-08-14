"""并行 subagent 编排（多单词并行记忆）。

当用户一次请求里包含多个彼此独立的子任务（典型：一次要记多个英语单词）时，
先用 :class:`Decomposer` 把整句拆成若干**自包含**的子任务指令，再由
:class:`Orchestrator` 用线程池并行执行——每个子任务就是一次 ``Executor.run``。

设计要点：
- 分解器基于 LLM（``json_object`` 模式，风格对齐 selector），单任务或任何异常都回退为
  ``[user_input]``，保证不改变既有单请求行为、且永不让 REPL 崩溃。
- 并发用 ``ThreadPoolExecutor``：``Executor`` 每次 run 无实例可变状态、tools 是纯函数、
  ``LLM.client`` HTTP 线程安全，故单个共享 executor 可安全跨线程复用。
- 结果按**原始词序**回填展示（不依赖完成顺序）；单个子任务失败只标记该条，不拖垮整批。
- 自进化不在这里做——多线程写同一 config.json 会竞态，故进化留到批次结束后由 REPL 主线程
  统一调用一次。
"""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .executor import Executor
from .llm import LLM
from .loader import SkillMeta

log = logging.getLogger("harness.orchestrator")

__all__ = ["Decomposer", "Orchestrator", "SubTaskResult"]

_DEFAULT_MAX_WORKERS = 4
_DEFAULT_MAX_SUBTASKS = 8

DECOMPOSER_SYSTEM = """你是一个任务分解器。用户的一句话可能包含【多个彼此独立、可并行完成的子任务】，
也可能只是【一个单一任务】。请把它拆成一组自包含的子任务指令。

【拆分规则】
1. 每个子任务必须是一条自包含的自然语言指令，读起来像用户单独发来的一句话，
   必须自带该子任务所需的全部信息（如具体单词 + 该词的个性化要求）。
2. 只有当子任务之间【真正独立、无先后依赖】时才拆分（典型：一次要记多个不同的英语单词）。
3. 若用户其实只是一个任务（哪怕句子很长、含多个修饰要求），不要拆分，tasks 只放一个元素，
   且该元素尽量【原样保留用户的完整表述】。
4. 不要臆造用户没提到的任务；不要把同一个单词拆成多条；最多输出 8 个子任务。
5. 每个子任务要保留原句里针对该对象的个性化要求（例如"benefit 要词根和派生词"）。

【输出格式】必须输出合法 JSON：
- tasks: 字符串数组，每个元素是一条子任务指令；单任务时长度为 1
- reason: 一句话说明（中文）

示例：
输入"记一下 abandon、benefit、resilient 这几个单词"
→ {"tasks":["记一下 abandon 这个单词","记一下 benefit 这个单词","记一下 resilient 这个单词"],"reason":"三个独立单词"}
输入"帮我记 apple orange banana"
→ {"tasks":["帮我记 apple 这个单词","帮我记 orange 这个单词","帮我记 banana 这个单词"],"reason":"三个独立单词"}
输入"记一下 resilient，要词根和联想记忆"
→ {"tasks":["记一下 resilient，要词根和联想记忆"],"reason":"单一任务，保留个性化要求"}
输入"记 benefit，另外 abandon 也帮我记，benefit 要多给派生词"
→ {"tasks":["记 benefit，要多给派生词","记 abandon 这个单词"],"reason":"两个独立单词，保留 benefit 的个性化要求"}
"""


@dataclass
class SubTaskResult:
    """单个 subagent 的执行结果，保留原始顺序索引用于按序展示。"""

    index: int
    sub_task: str
    ok: bool
    summary: str


class Decomposer:
    """基于 LLM 的任务分解器：把一句话拆成若干自包含子任务指令。"""

    def __init__(self, llm: LLM, max_subtasks: int = _DEFAULT_MAX_SUBTASKS):
        self.llm = llm
        self.max_subtasks = max_subtasks

    def decompose(self, user_input: str) -> list[str]:
        """返回长度 >=1 的子任务列表；单任务或任何失败都回退为 ``[user_input]``。"""
        try:
            resp = self.llm.chat(
                messages=[
                    {"role": "system", "content": DECOMPOSER_SYSTEM},
                    {"role": "user", "content": user_input},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("[decompose] LLM call failed, fallback to single task: %s", e)
            return [user_input]

        raw = resp.choices[0].message.content or "{}"
        data = self._safe_parse(raw)
        tasks = data.get("tasks")
        if not isinstance(tasks, list):
            log.info("[decompose] no valid tasks, fallback to single task")
            return [user_input]

        # 清洗：仅保留非空字符串、去空白、保序去重、截断
        cleaned = []
        for t in tasks:
            if isinstance(t, str) and t.strip():
                cleaned.append(t.strip())
        cleaned = list(dict.fromkeys(cleaned))[: self.max_subtasks]

        if len(cleaned) <= 1:
            # 单任务：原样保留用户输入，走原快速路径
            return [user_input]
        log.info("[decompose] split into %d subtasks: %s", len(cleaned), cleaned)
        return cleaned

    @staticmethod
    def _safe_parse(raw: str) -> dict:
        """三级兜底 JSON 解析：json.loads → 正则抓 {...} → {}。"""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            return {}


def _env_max_workers() -> int:
    """读 HARNESS_MAX_WORKERS，非法/缺失回退默认值。"""
    raw = os.getenv("HARNESS_MAX_WORKERS")
    if not raw:
        return _DEFAULT_MAX_WORKERS
    try:
        n = int(raw)
        return n if n >= 1 else _DEFAULT_MAX_WORKERS
    except ValueError:
        log.warning("[orchestrator] invalid HARNESS_MAX_WORKERS=%r, use default %d",
                    raw, _DEFAULT_MAX_WORKERS)
        return _DEFAULT_MAX_WORKERS


class Orchestrator:
    """用线程池并行执行多个 subagent（每个子任务一次 executor.run），按序收集结果。"""

    def __init__(self, executor: Executor, max_workers: int | None = None):
        self.executor = executor
        self.max_workers = max_workers or _env_max_workers()

    def run_parallel(self, skill: SkillMeta, sub_tasks: list[str]) -> list[SubTaskResult]:
        """并发跑各子任务，按**原始顺序**返回结果；单个失败不影响其它。"""
        n = len(sub_tasks)
        workers = max(1, min(self.max_workers, n))
        results: list[SubTaskResult | None] = [None] * n  # 预分配，用索引回填保序
        log.info("[orchestrator] running %d subtasks with max_workers=%d", n, workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_idx = {
                pool.submit(self._run_one, skill, i, task): i
                for i, task in enumerate(sub_tasks)
            }
            for fut in as_completed(future_to_idx):
                i = future_to_idx[fut]
                try:
                    results[i] = fut.result()  # _run_one 内已兜底，正常不抛
                except Exception as e:  # noqa: BLE001  双保险：绝不让一个失败拖垮整批
                    log.exception("[orchestrator] subtask %d crashed", i)
                    results[i] = SubTaskResult(
                        i, sub_tasks[i], ok=False,
                        summary=f"子任务异常：{type(e).__name__}: {e}",
                    )
        return [r for r in results if r is not None]

    def _run_one(self, skill: SkillMeta, index: int, sub_task: str) -> SubTaskResult:
        """单个 subagent：跑一次 executor.run，识别软失败串，异常兜底为失败结果。"""
        try:
            summary = self.executor.run(skill, sub_task)
            ok = not (summary.startswith("执行中断") or summary.startswith("(达到最大迭代"))
            return SubTaskResult(index, sub_task, ok=ok, summary=summary)
        except Exception as e:  # noqa: BLE001
            log.exception("[orchestrator] subtask %d failed", index)
            return SubTaskResult(index, sub_task, ok=False,
                                 summary=f"执行失败：{type(e).__name__}: {e}")
