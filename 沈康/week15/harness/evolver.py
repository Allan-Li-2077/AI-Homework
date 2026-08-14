"""
Skill 自进化器（self-evolution）——结构化指令版。

每次成功执行一个 skill 后，由 REPL 调用 :meth:`SkillEvolver.maybe_evolve`：
让 LLM 评估该 skill 的渲染配置 ``config.json`` 是否值得优化（版面顺序、各版块数量下限、
可选版块开关）。模型**不输出任何多行文本**，只输出一组**结构化指令**（枚举 op + 标量参数），
由本模块做 schema 校验后应用到 ``config.json``。若发生改动，则：

1. 先把当前 ``config.json`` 按序号备份到 ``.skill_versions/<skill名>/NNNN_config.json``；
2. 把应用指令后的新配置写回 ``<skill.dir>/config.json``；
3. SKILL.md（body）完全不动——数量/顺序改由 config 决定，故无需让缓存失效。

设计动机：早期"让模型吐整段 SKILL.md body"的做法会踩到 JSON 里塞多行文本的坑
（模型用 ``\\[NEWLINE]`` 哨兵代替真实换行，把整份说明压成一行乱码）。改为结构化指令后，
所有值都是 int / bool / 短枚举，JSON 里不存在多行字符串字段，从根上消除该类损坏。

任何异常都不应影响主流程——REPL 侧用 try/except 包裹调用。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .llm import LLM
from .loader import SkillMeta

log = logging.getLogger("harness.evolver")

__all__ = ["SkillEvolver", "apply_edits", "validate_edit", "explain_invalid_edit", "loads_jsonc"]

# 匹配 // 行注释与 /* */ 块注释，但保护字符串字面量内的同形字符（如 URL 里的 //）。
_JSONC_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"'      # 双引号字符串（含转义），整体跳过不动
    r"|//[^\n]*"              # 行注释
    r"|/\*.*?\*/",           # 块注释
    re.DOTALL,
)


def _strip_json_comments(text: str) -> str:
    """剔除 JSONC 风格的 // 与 /* */ 注释；字符串字面量内的内容原样保留。"""
    def _sub(m: re.Match) -> str:
        tok = m.group(0)
        return tok if tok.startswith('"') else ""

    return _JSONC_TOKEN.sub(_sub, text)


def loads_jsonc(text: str) -> dict:
    """容错解析：先按标准 JSON，失败再剔除注释后重试。仍失败则抛 JSONDecodeError。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_strip_json_comments(text))

# ── 领域模型：可寻址的版块与可调项（与 make_memo.py 保持一致）────────────────
_CANON_SECTIONS = ("root", "deriv", "mnemonic", "association", "example")
_CORE_SECTIONS = ("deriv", "mnemonic")            # 核心版块，禁止关闭
_OPTIONAL_SECTIONS = ("root", "association", "example")
_COUNT_KEYS = ("deriv", "mnemonic", "example", "syn", "ant", "theme")
_COUNT_MIN, _COUNT_MAX = 1, 20

# 备份文件名形如 0001_config.json
_VERSION_RE = re.compile(r"^(\d{4})_config\.json$")

EVOLVER_SYSTEM = """你是一个 skill 维护者。下面给你一个单词记忆卡 skill 的**渲染配置**（JSON），
以及用户本次的实际使用请求与执行结果摘要。请判断这份配置是否有**明显值得优化**的地方，
并只用【结构化指令】表达你的修改意图。

配置含义：
- section_order: HTML 卡片各版块的展示顺序，取值只能是这些名字的排列：
  root(词根词缀) / deriv(派生词) / mnemonic(联想记忆) / association(关联词) / example(例句)。
- min_counts: 各内容的数量下限，键为 deriv/mnemonic/example/syn/ant/theme，值为 1-20 的整数。
- optional_sections: 可选版块是否显示，只有 root / association / example 可开关。

【可用指令 op（只能用这些，参数只能是数字/布尔/上面枚举里的短词）】
1. {"op":"set_min_count","section":"<deriv|mnemonic|example|syn|ant|theme>","value":<1-20整数>}
2. {"op":"reorder_sections","order":["<上面5个版块名的一个完整排列>"]}
3. {"op":"toggle_optional_section","section":"<root|association|example>","enabled":<true|false>}

【硬性约束（违反即视为不合格，宁可不改）】
1. 绝对不要输出任何多行文本、不要输出 SKILL.md 正文、不要新增未列出的字段。
2. reorder_sections 的 order 必须恰好是那 5 个版块名的排列（不增不减不重复）。
3. deriv(派生词) 与 mnemonic(联想记忆) 是核心，禁止 toggle 关闭它们。
4. 只有确有明显收益才优化；配置已合理时返回 should_evolve=false，edits 给空数组。

【输出格式】必须输出合法 JSON：
- should_evolve: 布尔
- reason: 一句话说明（中文）
- edits: 指令数组（should_evolve=false 时为 []）
"""


# ── 纯函数：校验与应用（确定性、可单测，不依赖 LLM）──────────────────────────
def validate_edit(edit: dict) -> bool:
    """校验单条结构化指令是否合规（枚举/范围/排列完整性/核心版块保护）。"""
    if not isinstance(edit, dict):
        return False
    op = edit.get("op")
    if op == "set_min_count":
        sec = edit.get("section")
        val = edit.get("value")
        return (
            sec in _COUNT_KEYS
            and isinstance(val, int)
            and not isinstance(val, bool)
            and _COUNT_MIN <= val <= _COUNT_MAX
        )
    if op == "reorder_sections":
        order = edit.get("order")
        return (
            isinstance(order, list)
            and len(order) == len(_CANON_SECTIONS)
            and set(order) == set(_CANON_SECTIONS)
        )
    if op == "toggle_optional_section":
        sec = edit.get("section")
        enabled = edit.get("enabled")
        # 只有可选版块可开关；核心版块即使出现在可选名单外也不接受
        return sec in _OPTIONAL_SECTIONS and isinstance(enabled, bool)
    return False


def explain_invalid_edit(edit: dict) -> str:
    """对不合规指令给出一句人类可读的中文原因（用于给用户反馈，不影响校验逻辑）。"""
    if not isinstance(edit, dict):
        return "指令格式不是对象"
    op = edit.get("op")
    if op == "set_min_count":
        sec, val = edit.get("section"), edit.get("value")
        if sec not in _COUNT_KEYS:
            return f"版块名「{sec}」不可调数量（可调：{'/'.join(_COUNT_KEYS)}）"
        if isinstance(val, bool) or not isinstance(val, int):
            return f"数量值「{val}」不是整数"
        if not (_COUNT_MIN <= val <= _COUNT_MAX):
            return f"{sec} 数量 {val} 超出允许范围 {_COUNT_MIN}-{_COUNT_MAX}"
        return "未知原因"
    if op == "reorder_sections":
        return f"版面顺序必须是这 5 个版块的完整排列：{'/'.join(_CANON_SECTIONS)}"
    if op == "toggle_optional_section":
        sec = edit.get("section")
        if sec in _CORE_SECTIONS:
            return f"核心版块「{sec}」禁止隐藏"
        return f"只有可选版块可开关（可开关：{'/'.join(_OPTIONAL_SECTIONS)}），且 enabled 必须是布尔"
    return f"未知指令 op「{op}」"


def apply_edits(config: dict, edits: list) -> tuple[dict, list[str]]:
    """把已校验通过的指令应用到 config 的**深拷贝**，返回 (新配置, 变更说明列表)。

    只应用 validate_edit 通过的指令；不合规的整批已在上层拒绝，这里假定逐条合规。
    """
    cfg = json.loads(json.dumps(config))  # 深拷贝，绝不原地改
    cfg.setdefault("section_order", list(_CANON_SECTIONS))
    cfg.setdefault("min_counts", {})
    cfg.setdefault("optional_sections", {})
    changes: list[str] = []
    for e in edits:
        op = e["op"]
        if op == "set_min_count":
            sec, val = e["section"], e["value"]
            old = cfg["min_counts"].get(sec)
            if old != val:
                cfg["min_counts"][sec] = val
                changes.append(f"{sec} 数量下限 {old}→{val}")
        elif op == "reorder_sections":
            if cfg.get("section_order") != e["order"]:
                cfg["section_order"] = list(e["order"])
                changes.append("调整版面顺序为 " + "→".join(e["order"]))
        elif op == "toggle_optional_section":
            sec, enabled = e["section"], e["enabled"]
            old = cfg["optional_sections"].get(sec)
            if old != enabled:
                cfg["optional_sections"][sec] = enabled
                changes.append(f"{sec} 版块{'显示' if enabled else '隐藏'}")
    return cfg, changes


class SkillEvolver:
    """基于结构化指令自动优化 skill 的 config.json，改前按序号备份旧配置。"""

    def __init__(self, llm: LLM, root: Path):
        self.llm = llm
        self.root = root
        self.versions_root = root / ".skill_versions"

    def maybe_evolve(self, skill: SkillMeta, user_input: str, summary: str) -> str | None:
        """评估并（若值得）应用结构化优化到 config.json，返回中文提示，否则 None。

        若 config.json 缺失或即使剔除注释后仍无法解析为合法 JSON，返回一条**警告提示**
        （而非静默跳过），以便 REPL 明确告知用户"本次未进化"及原因。
        """
        config_path = skill.dir / "config.json"
        try:
            old_text = config_path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("[evolve] cannot read config.json, skip: %s (%s)", config_path, e)
            return None
        try:
            config = loads_jsonc(old_text)
        except json.JSONDecodeError as e:
            log.warning("[evolve] config.json is invalid JSON, skip evolve: %s (%s)",
                        config_path, e)
            return (f"⚠️ 未进化 skill「{skill.name}」：其 config.json 不是合法 JSON"
                    f"（{e}）。请修正后再试——注意 JSON 不支持 // 或 /* */ 注释，"
                    f"如需说明可写进 _comment 字段。")

        decision = self._ask_llm(config, user_input, summary)
        if decision is None:
            return None
        if not decision.get("should_evolve"):
            log.info("[evolve] skill=%s should_evolve=false reason=%s",
                     skill.name, decision.get("reason", ""))
            return None

        edits = decision.get("edits")
        reason = str(decision.get("reason") or "")
        if not isinstance(edits, list) or not edits:
            log.info("[evolve] skill=%s no edits provided, skip", skill.name)
            return None
        # 原子性：任一条不合规 → 整批拒绝，绝不半改；并把原因反馈给用户（不再静默）
        for e in edits:
            if not validate_edit(e):
                why = explain_invalid_edit(e)
                log.warning("[evolve] skill=%s invalid edit %r (%s), reject whole batch",
                            skill.name, e, why)
                return (f"⚠️ 未进化 skill「{skill.name}」：本次修改被拒绝（{why}）。"
                        f"配置保持不变。")

        new_config, changes = apply_edits(config, edits)
        if not changes:
            log.info("[evolve] skill=%s edits are no-ops, skip", skill.name)
            return None

        backup_path = self._backup(skill, old_text)
        config_path.write_text(
            json.dumps(new_config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rel_backup = backup_path.relative_to(self.root).as_posix()
        change_str = "；".join(changes)
        log.info("[evolve] skill=%s evolved config, backup=%s changes=%s",
                 skill.name, rel_backup, change_str)
        return (f"已根据本次使用自动优化 skill「{skill.name}」的渲染配置"
                f"（{change_str}；原因：{reason}），旧配置已备份为 {rel_backup}")

    def _ask_llm(self, config: dict, user_input: str, summary: str) -> dict | None:
        """调 LLM 评估，返回解析后的决策 dict；调用/解析失败返回 None。"""
        user_msg = (
            f"【当前渲染配置 config.json】\n{json.dumps(config, ensure_ascii=False, indent=2)}\n\n"
            f"【用户本次请求】\n{user_input}\n\n"
            f"【本次执行结果摘要】\n{summary}"
        )
        try:
            resp = self.llm.chat(
                messages=[
                    {"role": "system", "content": EVOLVER_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("[evolve] LLM call failed: %s", e)
            return None
        raw = resp.choices[0].message.content or "{}"
        return self._safe_parse(raw)

    def _backup(self, skill: SkillMeta, full_text: str) -> Path:
        """把当前 config.json 按序号备份到 .skill_versions/<skill名>/NNNN_config.json。"""
        target_dir = self.versions_root / skill.name
        target_dir.mkdir(parents=True, exist_ok=True)
        idx = self._next_index(target_dir)
        backup_path = target_dir / f"{idx:04d}_config.json"
        backup_path.write_text(full_text, encoding="utf-8")
        return backup_path

    @staticmethod
    def _next_index(target_dir: Path) -> int:
        """扫描已有 NNNN_config.json，返回 max+1（从 1 起）。"""
        max_idx = 0
        for p in target_dir.iterdir():
            m = _VERSION_RE.match(p.name)
            if m:
                max_idx = max(max_idx, int(m.group(1)))
        return max_idx + 1

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
