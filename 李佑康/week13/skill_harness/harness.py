from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .catalog import SkillCatalog
from .llm import LLMClient, OpenAIResponsesClient
from .models import HarnessEvent, HarnessResult, Skill


class ProgressiveSkillHarness:
    """
    三阶段 Skill 执行器：
    1. discover: 只读取 front matter；
    2. route/load: 只加载命中 Skill 的完整指令；
    3. execute: 脚本按协议申请资源，Harness 才读取对应文件。
    """

    def __init__(
        self,
        skills_dir: str | Path,
        *,
        timeout: float = 10.0,
        max_resource_rounds: int = 5,
        llm_client: LLMClient | None = None,
    ):
        self.skills_dir = Path(skills_dir).resolve()
        self.timeout = timeout
        self.max_resource_rounds = max_resource_rounds
        self.llm_client = llm_client

    def list_skills(self):
        events: list[HarnessEvent] = []
        return SkillCatalog(self.skills_dir, events).discover()

    def run(self, request: str, skill_name: str | None = None) -> HarnessResult:
        events: list[HarnessEvent] = []
        catalog = SkillCatalog(self.skills_dir, events)
        catalog.discover()
        metadata = catalog.choose(request, skill_name)
        skill = catalog.load(metadata)
        if skill.metadata.executor == "llm":
            output = self._execute_llm(skill, request, events)
        else:
            output = self._execute_python(skill, request, events)
        return HarnessResult(skill=metadata.name, output=output, events=events)

    def _safe_child(self, root: Path, relative: str) -> Path:
        candidate = (root / relative).resolve()
        if candidate == root or root not in candidate.parents:
            raise ValueError(f"路径越界: {relative}")
        return candidate

    def _execute_python(
        self, skill: Skill, request: str, events: list[HarnessEvent]
    ) -> Any:
        assert skill.metadata.entrypoint is not None
        entrypoint = self._safe_child(skill.metadata.root, skill.metadata.entrypoint)
        if entrypoint.suffix != ".py" or not entrypoint.is_file():
            raise ValueError("entrypoint 必须是 Skill 目录内存在的 .py 文件")

        resources: dict[str, str] = {}
        for round_number in range(1, self.max_resource_rounds + 1):
            payload = {
                "request": request,
                "instructions": skill.instructions,
                "resources": resources,
            }
            events.append(
                HarnessEvent(
                    "execute",
                    skill.metadata.name,
                    f"执行第 {round_number} 轮，已加载 {len(resources)} 个资源",
                )
            )
            completed = subprocess.run(
                [sys.executable, "-I", str(entrypoint)],
                input=json.dumps(payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.timeout,
                cwd=skill.metadata.root,
                check=False,
            )
            if completed.returncode != 0:
                error = completed.stderr.strip() or "无错误输出"
                raise RuntimeError(f"Skill 执行失败 ({completed.returncode}): {error}")
            try:
                response = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Skill 输出必须是单个 JSON 对象") from exc
            if not isinstance(response, dict):
                raise RuntimeError("Skill 输出必须是 JSON 对象")

            needed = response.get("need_resources")
            if needed is not None:
                if not isinstance(needed, list) or not all(
                    isinstance(path, str) for path in needed
                ):
                    raise RuntimeError("need_resources 必须是字符串数组")
                unloaded = [path for path in needed if path not in resources]
                if not unloaded:
                    raise RuntimeError("Skill 重复申请已加载资源，无法继续")
                for relative in unloaded:
                    path = self._safe_child(skill.metadata.root, relative)
                    if not path.is_file():
                        raise FileNotFoundError(f"Skill 申请的资源不存在: {relative}")
                    resources[relative] = path.read_text(encoding="utf-8")
                    events.append(
                        HarnessEvent(
                            "load_resource", skill.metadata.name, f"按需加载 {relative}"
                        )
                    )
                continue
            if "result" not in response:
                raise RuntimeError("Skill 必须返回 result 或 need_resources")
            events.append(HarnessEvent("complete", skill.metadata.name, "执行完成"))
            return response["result"]
        raise RuntimeError("超过最大资源加载轮数")

    def _resource_index(self, skill: Skill) -> list[dict[str, object]]:
        reference_root = skill.metadata.root / "references"
        if not reference_root.is_dir():
            return []
        return [
            {
                "path": path.relative_to(skill.metadata.root).as_posix(),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(reference_root.rglob("*"))
            if path.is_file()
        ]

    @staticmethod
    def _parse_llm_json(text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(lines[1:-1]).strip()
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM 没有返回合法 JSON: {text[:200]}") from exc
        if not isinstance(value, dict):
            raise RuntimeError("LLM 响应必须是 JSON 对象")
        return value

    def _execute_llm(
        self, skill: Skill, request: str, events: list[HarnessEvent]
    ) -> Any:
        client = self.llm_client or OpenAIResponsesClient()
        resources: dict[str, str] = {}
        resource_index = self._resource_index(skill)
        system = f"""你是渐进式 Skill Harness 中的执行模型。

Skill 指令：
{skill.instructions}

你只能返回一个 JSON 对象，不要使用 Markdown。协议只有两种动作：
1. 需要参考资源时：{{"action":"load_resources","paths":["references/a.md"]}}
2. 完成任务时：{{"action":"finish","result":任意合法 JSON 值}}

只能申请资源索引中存在的路径；已有资源足够时必须 finish。
"""
        for round_number in range(1, self.max_resource_rounds + 1):
            input_text = json.dumps(
                {
                    "request": request,
                    "resource_index": resource_index,
                    "loaded_resources": resources,
                },
                ensure_ascii=False,
            )
            events.append(
                HarnessEvent(
                    "llm_call",
                    skill.metadata.name,
                    f"第 {round_number} 次调用模型，已加载 {len(resources)} 个资源",
                )
            )
            response = self._parse_llm_json(client.complete(system, input_text))
            action = response.get("action")
            if action == "finish":
                if "result" not in response:
                    raise RuntimeError("finish 动作缺少 result")
                events.append(HarnessEvent("complete", skill.metadata.name, "LLM 执行完成"))
                return response["result"]
            if action != "load_resources":
                raise RuntimeError(f"不支持的 LLM action: {action}")
            paths = response.get("paths")
            if not isinstance(paths, list) or not all(isinstance(x, str) for x in paths):
                raise RuntimeError("load_resources.paths 必须是字符串数组")
            allowed = {item["path"] for item in resource_index}
            unloaded = [path for path in paths if path not in resources]
            if not unloaded:
                raise RuntimeError("LLM 重复申请已加载资源")
            for relative in unloaded:
                if relative not in allowed:
                    raise ValueError(f"LLM 申请了资源索引外的路径: {relative}")
                path = self._safe_child(skill.metadata.root, relative)
                resources[relative] = path.read_text(encoding="utf-8")
                events.append(
                    HarnessEvent("load_resource", skill.metadata.name, f"按需加载 {relative}")
                )
        raise RuntimeError("超过最大 LLM/资源加载轮数")
