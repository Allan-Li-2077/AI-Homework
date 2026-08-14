"""
翻译主 Agent：解析意图 → 调用独立子 Skill（translate-en/ja/fr/ko/ru）→ 汇总。

开关 TRANSLATE_PARALLEL / set_parallel_enabled：
  True  → ThreadPoolExecutor 并行调用子 Skill
  False → 按目标语言顺序串行调用
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.sub_agents.translate.config import describe_mode, get_parallel_enabled
from src.sub_agents.translate.format_reply import format_translation_reply
from src.sub_agents.translate.lang_worker import SubAgentResult
from src.sub_agents.translate.parse import (
    CODE_TO_SKILL,
    LANGS,
    UNSUPPORTED_MSG,
    parse_query,
)
from src.sub_agents.translate.skill_invoke import invoke_lang_skill, list_sub_skills


def _with_display(result: dict) -> dict:
    result["display"] = format_translation_reply(result)
    return result


class TranslateMainAgent:
    """主 agent：只做分发与结果汇总；翻译由独立子 Skill 执行。"""

    agent_name = "translate-main-agent"
    skill_name = "multi-lang-translate"

    def run(
        self,
        text: str,
        *,
        parallel: bool | None = None,
        dry_run: bool = False,
    ) -> dict:
        t0 = time.time()
        parsed = parse_query(text)
        mode_parallel = get_parallel_enabled() if parallel is None else bool(parallel)
        mode = "parallel" if mode_parallel else "serial"

        base_meta = {
            "main_agent": self.agent_name,
            "main_skill": self.skill_name,
            "mode": mode,
            "parallel": mode_parallel,
            "switch": describe_mode(),
            "sub_skills_planned": [],
            "sub_skills_catalog": list_sub_skills(),
        }

        if not parsed["has_intent"] and not parsed["targets"] and not parsed["unsupported"]:
            return _with_display({
                "ok": False,
                "error": "未检测到翻译意图。请使用如「翻译成英文：……」的说法。",
                "supported": parsed["supported"],
                **base_meta,
            })

        unsupported = parsed["unsupported"]
        targets = parsed["targets"]

        if unsupported and not targets:
            return _with_display({
                "ok": False,
                "error": UNSUPPORTED_MSG,
                "unsupported": unsupported,
                "source": parsed["source"],
                "supported": parsed["supported"],
                "metrics": {"elapsed_s": round(time.time() - t0, 3)},
                **base_meta,
            })

        if not targets and not unsupported:
            labels = "、".join(LANGS[c][0] for c in LANGS)
            return _with_display({
                "ok": False,
                "error": f"未识别目标语言。支持：{labels}。示例：翻译成英文、日文：……",
                "source": parsed["source"],
                "supported": parsed["supported"],
                "metrics": {"elapsed_s": round(time.time() - t0, 3)},
                **base_meta,
            })

        if not parsed["source"]:
            return _with_display({
                "ok": False,
                "error": "未找到待翻译的中文正文，请在指令后附上要翻译的内容。",
                "targets": targets,
                "unsupported": unsupported,
                "supported": parsed["supported"],
                "metrics": {"elapsed_s": round(time.time() - t0, 3)},
                **base_meta,
            })

        base_meta["sub_skills_planned"] = [CODE_TO_SKILL[c] for c in targets]

        results = self._dispatch(
            parsed["source"],
            targets,
            parallel=mode_parallel,
            dry_run=dry_run,
        )

        translations: dict = {}
        sub_runs: list[dict] = []
        total_tokens = 0
        all_ok = True
        for code in targets:
            r = results[code]
            sub_runs.append(
                {
                    "skill": getattr(r, "skill", CODE_TO_SKILL[code]),
                    "agent": r.agent,
                    "code": r.code,
                    "label": r.label,
                    "ok": r.ok,
                    "elapsed_s": r.elapsed_s,
                    "metrics": r.metrics,
                    "error": r.error,
                }
            )
            if r.ok:
                translations[code] = {
                    "label": r.label,
                    "text": r.text,
                    "agent": r.agent,
                    "skill": getattr(r, "skill", CODE_TO_SKILL[code]),
                }
                total_tokens += int((r.metrics or {}).get("total_tokens", 0) or 0)
            else:
                all_ok = False
                translations[code] = {
                    "label": r.label,
                    "text": "",
                    "agent": r.agent,
                    "skill": getattr(r, "skill", CODE_TO_SKILL[code]),
                    "error": r.error,
                }

        elapsed = round(time.time() - t0, 3)
        out: dict = {
            "ok": all_ok,
            "source": parsed["source"],
            "targets": targets,
            "translations": translations,
            "sub_skill_runs": sub_runs,
            "sub_agent_runs": sub_runs,  # 兼容旧字段
            "metrics": {
                "elapsed_s": elapsed,
                "total_tokens": total_tokens,
                "mode": mode,
                "sub_skill_count": len(targets),
            },
            **base_meta,
        }
        if unsupported:
            out["unsupported"] = unsupported
            out["unsupported_message"] = UNSUPPORTED_MSG
            if all_ok:
                out["ok"] = True
            out["warning"] = UNSUPPORTED_MSG
        if not all_ok:
            failed = [c for c in targets if not results[c].ok]
            out["error"] = "部分子 Skill 失败：" + "、".join(
                f"{results[c].label}/{getattr(results[c], 'skill', CODE_TO_SKILL[c])}"
                f"({results[c].error})"
                for c in failed
            )
        return _with_display(out)

    def _dispatch(
        self,
        source: str,
        targets: list[str],
        *,
        parallel: bool,
        dry_run: bool,
    ) -> dict[str, SubAgentResult]:
        if not parallel or len(targets) <= 1:
            return {
                code: invoke_lang_skill(code, source, dry_run=dry_run)
                for code in targets
            }

        results: dict[str, SubAgentResult] = {}

        def _run(code: str) -> tuple[str, SubAgentResult]:
            result = invoke_lang_skill(code, source, dry_run=dry_run)
            if result.code != code:
                result = SubAgentResult(
                    agent=result.agent,
                    skill=CODE_TO_SKILL[code],
                    code=code,
                    label=LANGS[code][0],
                    ok=False,
                    error=f"子 Skill 返回语种不匹配：期望 {code}，实际 {result.code}",
                )
            return code, result

        with ThreadPoolExecutor(
            max_workers=len(targets), thread_name_prefix="tr-sub"
        ) as pool:
            future_map = {pool.submit(_run, code): code for code in targets}
            for fut in as_completed(future_map):
                code = future_map[fut]
                try:
                    got_code, result = fut.result()
                    results[got_code] = result
                except Exception as e:
                    results[code] = SubAgentResult(
                        agent=f"{CODE_TO_SKILL[code]}-agent",
                        skill=CODE_TO_SKILL[code],
                        code=code,
                        label=LANGS[code][0],
                        ok=False,
                        error=str(e),
                    )
        for code in targets:
            if code not in results:
                results[code] = SubAgentResult(
                    agent=f"{CODE_TO_SKILL[code]}-agent",
                    skill=CODE_TO_SKILL[code],
                    code=code,
                    label=LANGS[code][0],
                    ok=False,
                    error="并行执行未返回结果",
                )
        return results
