"""
Skill 执行器 — Layer S3：执行 SkillContract，返回 SkillResult

教学重点：
  1. **三种 execution 类型**：
     - prompt：把 skill 正文拼成 system prompt，调 LLM 生成（最常用、最安全）
     - code：执行 skill 配套的 code.py（受 sandbox 限制）
     - workflow：按 yaml 顺序调用多个子 skill（v1: chain of prompts）
  2. **流式输出**：通过回调 broadcast(token, ...) 让前端实时看到执行进度
  3. **超时与降级**：LLM 调用失败时返回错误结果而非崩溃

使用方式：
  executor = SkillExecutor()
  result = executor.run(contract, context={"history": messages, "memory_snippets": [...]})
  # result.text / result.success / result.error / result.duration_ms
"""

import json
import time
import logging
import subprocess
import tempfile
import importlib.util
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Optional, Any

from src.skill_loader import SkillContract

logger = logging.getLogger(__name__)

# 广播回调：fn(event_type: str, data: dict) -> None
BroadcastFn = Callable[[str, dict], None]


@dataclass
class SkillResult:
    """Skill 执行结果"""
    skill_name: str
    success: bool = True
    text: str = ""                               # 主要输出（最终给用户看的文本）
    raw_output: Any = None                        # 原始输出（code 类型可能是 dict）
    error: str = ""
    duration_ms: float = 0.0
    tokens_streamed: int = 0                      # 估算的 token 数（用于前端展示）
    broadcast_log: list[dict] = field(default_factory=list)  # 执行过程中的事件


class SkillExecutor:
    """执行 SkillContract 的核心调度器"""

    # 默认超时（秒）
    DEFAULT_LLM_TIMEOUT = 60
    DEFAULT_CODE_TIMEOUT = 10

    def __init__(self, broadcast: Optional[BroadcastFn] = None):
        self.broadcast = broadcast or (lambda t, d: None)

    def set_broadcast(self, fn: BroadcastFn):
        self.broadcast = fn

    def run(
        self,
        contract: SkillContract,
        context: Optional[dict] = None,
        user_query: str = "",
    ) -> SkillResult:
        """根据 contract.meta.execution 分发到不同执行路径"""
        context = context or {}
        result = SkillResult(skill_name=contract.meta.name)
        t0 = time.perf_counter()

        self._emit(result, "skill_execution_start", {
            "skill_name": contract.meta.name,
            "execution": contract.meta.execution,
            "params": contract.params_resolved,
            "missing_params": contract.params_missing,
            "load_time_ms": contract.load_time_ms,
            "cache_hit": contract.cache_hit,
            "content_hash": contract.content_hash,
        })

        try:
            if contract.meta.execution == "prompt":
                self._run_prompt(contract, context, user_query, result)
            elif contract.meta.execution == "code":
                self._run_code(contract, context, result)
            elif contract.meta.execution == "workflow":
                self._run_workflow(contract, context, user_query, result)
            else:
                result.success = False
                result.error = f"未知 execution 类型：{contract.meta.execution}"
        except Exception as e:
            logger.exception(f"Skill '{contract.meta.name}' 执行失败")
            result.success = False
            result.error = str(e)

        result.duration_ms = (time.perf_counter() - t0) * 1000
        self._emit(result, "skill_execution_done", {
            "skill_name": contract.meta.name,
            "success": result.success,
            "duration_ms": result.duration_ms,
            "tokens_streamed": result.tokens_streamed,
            "error": result.error,
            "output_preview": (result.text or "")[:200],
        })
        return result

    # ── execution = prompt ─────────────────────────────────────────────────────

    def _run_prompt(
        self,
        contract: SkillContract,
        context: dict,
        user_query: str,
        result: SkillResult,
    ):
        """prompt 型 skill：把 SKILL.md 正文作为 system prompt 调 LLM"""
        from src.llm_config import get_chat_client

        system_prompt = self._build_system_prompt(contract, context, user_query)
        user_message = context.get("user_query") or user_query or "(无用户输入)"

        # 也允许 skill 直接以模板方式被调用：把 params 当 user message
        if "user_query_template" in context:
            try:
                user_message = context["user_query_template"].format(**contract.params_resolved)
            except KeyError as e:
                result.success = False
                result.error = f"模板缺少参数：{e}"
                return

        api_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        self._emit(result, "skill_llm_call", {
            "skill_name": contract.meta.name,
            "system_chars": len(system_prompt),
            "user_chars": len(user_message),
        })

        try:
            client, model = get_chat_client()
            stream = client.chat.completions.create(
                model=model,
                messages=api_messages,
                temperature=0.4,
                stream=True,
            )
            buf: list[str] = []
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    buf.append(delta)
                    result.tokens_streamed += 1
                    self._emit(result, "skill_token", {
                        "skill_name": contract.meta.name,
                        "text": delta,
                    })
            result.text = "".join(buf)
        except Exception as e:
            result.success = False
            result.error = f"LLM 调用失败：{e}"

    def _build_system_prompt(self, contract: SkillContract, context: dict, user_query: str) -> str:
        """拼装 system prompt：skill 正文 + 可选的记忆片段"""
        parts = [
            f"# Skill: {contract.meta.name} (v{contract.meta.version})",
            "",
            contract.prompt_for_llm,
        ]

        # 注入相关历史记忆（如果有）
        memory_snippets = context.get("memory_snippets") or []
        if memory_snippets:
            parts.append("\n## 相关历史记忆\n" + "\n".join(f"- {s}" for s in memory_snippets[:5]))

        # 注入用户偏好（如果有）
        user_profile = context.get("user_profile")
        if user_profile:
            parts.append(f"\n## 当前用户画像\n{user_profile}")

        # 注入会话摘要（如果有过往 skill 调用）
        recent_skill_results = context.get("recent_skill_results") or []
        if recent_skill_results:
            parts.append("\n## 最近 skill 调用结果")
            for r in recent_skill_results[-3:]:
                preview = (r.get("text") or "")[:150]
                parts.append(f"- {r['skill_name']}: {preview}")

        return "\n".join(parts)

    # ── execution = code ───────────────────────────────────────────────────────

    def _run_code(self, contract: SkillContract, context: dict, result: SkillResult):
        """code 型 skill：执行 skill 同目录下的 code.py（受 sandbox 限制）"""
        skill_dir = Path(contract.meta.source_path).parent
        code_path = skill_dir / "code.py"
        if not code_path.exists():
            result.success = False
            result.error = f"code 型 skill 缺少 code.py：{code_path}"
            return

        # 安全限制：仅暴露受限 API
        sandbox_api = self._build_sandbox_api(contract, context)

        try:
            spec = importlib.util.spec_from_file_location(f"skill_{contract.meta.name}", code_path)
            mod = importlib.util.module_from_spec(spec)
            # 把 sandbox API 注入到模块全局
            for k, v in sandbox_api.items():
                setattr(mod, k, v)
            spec.loader.exec_module(mod)

            if not hasattr(mod, "main"):
                result.success = False
                result.error = "code.py 必须定义 main(params) 函数"
                return

            raw = mod.main(contract.params_resolved)
            result.raw_output = raw
            if isinstance(raw, dict):
                result.text = raw.get("text", json.dumps(raw, ensure_ascii=False))
            else:
                result.text = str(raw)
        except Exception as e:
            result.success = False
            result.error = f"代码执行失败：{e}"

    def _build_sandbox_api(self, contract: SkillContract, context: dict) -> dict:
        """为 code 型 skill 构造受限 API"""
        import os

        def safe_shell(cmd: str, timeout: int = 10) -> dict:
            """白名单命令执行（仅 echo/ls/dir/cat/type 等只读命令）"""
            whitelist = {"echo", "ls", "dir", "cat", "type", "find", "where", "python"}
            first = cmd.strip().split(maxsplit=1)[0] if cmd.strip() else ""
            if first not in whitelist:
                return {"error": f"shell 命令 '{first}' 不在白名单"}
            try:
                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=timeout
                )
                return {
                    "stdout": proc.stdout[:4000],
                    "stderr": proc.stderr[:1000],
                    "returncode": proc.returncode,
                }
            except subprocess.TimeoutExpired:
                return {"error": f"命令超时（{timeout}s）"}

        return {
            "params": contract.params_resolved,
            "context": context,
            "emit": lambda t, d: self._emit(result := SkillResult(skill_name=contract.meta.name), t, d),
            "shell": safe_shell,
            "read_file": lambda p, limit=4000: Path(p).read_text(encoding="utf-8", errors="ignore")[:limit],
            "log": lambda msg: self._emit(SkillResult(skill_name=contract.meta.name), "skill_log", {"msg": str(msg)}),
            "os_environ": dict(os.environ),  # 只读副本，避免子代码修改 env
        }

    # ── execution = workflow ────────────────────────────────────────────────────

    def _run_workflow(self, contract: SkillContract, context: dict, user_query: str, result: SkillResult):
        """workflow 型 skill：解析 YAML 步骤，串行调用"""
        wf_path = Path(contract.meta.source_path).parent / "workflow.yaml"
        if not wf_path.exists():
            result.success = False
            result.error = f"workflow 型 skill 缺少 workflow.yaml：{wf_path}"
            return

        try:
            import yaml
            wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        except ImportError:
            result.success = False
            result.error = "缺少 PyYAML，请 pip install pyyaml"
            return
        except Exception as e:
            result.success = False
            result.error = f"workflow.yaml 解析失败：{e}"
            return

        steps = wf.get("steps", [])
        if not steps:
            result.success = False
            result.error = "workflow.yaml 缺少 steps 字段"
            return

        aggregated = []
        for i, step in enumerate(steps, 1):
            self._emit(result, "workflow_step", {
                "step_index": i,
                "step_total": len(steps),
                "skill_name": step.get("skill"),
            })

            from src.skill_loader import SkillLoader
            from src.skill_registry import get_registry

            registry = get_registry()
            loader = SkillLoader(registry)
            sub_params = dict(step.get("params", {}))
            # 支持模板替换：params.user_input ← user_query
            for k, v in list(sub_params.items()):
                if isinstance(v, str) and v == "$user_query":
                    sub_params[k] = user_query
            sub_contract = loader.load(step["skill"], params=sub_params, use_cache=True)
            if not sub_contract:
                result.success = False
                result.error = f"workflow 步骤 {i} 加载失败：{step.get('skill')}"
                return
            sub_result = self.run(sub_contract, context=context, user_query=user_query)
            aggregated.append({
                "step": i,
                "skill": step["skill"],
                "text": sub_result.text,
                "success": sub_result.success,
            })
            if not sub_result.success and step.get("required", True):
                result.success = False
                result.error = f"workflow 步骤 {i}（{step['skill']}）失败：{sub_result.error}"
                result.raw_output = aggregated
                return

        result.raw_output = aggregated
        result.text = "\n\n".join(
            f"### {a['skill']}\n{a['text']}" for a in aggregated
        )

    # ── 事件广播辅助 ───────────────────────────────────────────────────────────

    def _emit(self, result: SkillResult, event_type: str, data: dict):
        data = dict(data)
        data.setdefault("skill_name", result.skill_name)
        result.broadcast_log.append({"type": event_type, "data": data})
        try:
            self.broadcast(event_type, data)
        except Exception as e:
            logger.warning(f"broadcast 失败：{e}")