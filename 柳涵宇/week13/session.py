from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import HarnessError, SkillNotFoundError
from .markdown import extract_skill_relative_paths, read_text
from .models import LoadedResource, LoadedSkill, SkillMeta, TraceEvent
from .registry import SkillRegistry
from .router import RouteCandidate, SkillRouter


class ProgressiveSkillHarness:
    """High-level progressive loading facade.

    Loading phases:
    1. Discover: read only each skill's front matter.
    2. Route: select candidate using metadata only.
    3. Load skill: read full SKILL.md for the selected skill only.
    4. Load resources: read references/data only when auto-selected or requested.
    5. Execute: adapters may run scripts without reading script source into context.
    """

    def __init__(self, skill_dirs: list[str | Path] | None = None, *, cwd: str | Path | None = None):
        self.cwd = Path(cwd or Path.cwd()).resolve()
        self.registry = SkillRegistry(skill_dirs, cwd=self.cwd)
        self.trace: list[TraceEvent] = self.registry.trace
        self._resource_cache: dict[tuple[str, str], LoadedResource] = {}

    def discover(self) -> list[SkillMeta]:
        return self.registry.discover()

    def route(self, request: str, *, top_k: int = 3) -> list[RouteCandidate]:
        skills = self.discover()
        router = SkillRouter(skills)
        candidates = router.route(request, top_k=top_k)
        self.trace.append(TraceEvent("route", f"routed request; {len(candidates)} candidate(s)"))
        return candidates

    def select(self, request: str, *, explicit_skill: str | None = None) -> RouteCandidate:
        skills = self.discover()
        router = SkillRouter(skills)
        selected = router.select(request, explicit_skill=explicit_skill)
        if selected is None:
            detail = f"No skill matched request: {request!r}"
            if explicit_skill:
                detail = f"Explicit skill not found: {explicit_skill}"
            raise SkillNotFoundError(detail)
        self.trace.append(TraceEvent("select", f"selected {selected.skill.name} (score={selected.score})"))
        return selected

    def load_skill(self, name: str) -> LoadedSkill:
        return self.registry.load_skill(name)

    def available_relative_paths(self, skill: LoadedSkill) -> list[str]:
        from_markdown = extract_skill_relative_paths(skill.markdown)
        from_dirs: list[str] = []
        for dirname in ("references", "scripts", "data", "assets"):
            directory = skill.meta.skill_dir / dirname
            if directory.exists():
                for path in sorted(directory.rglob("*")):
                    if path.is_file() and "node_modules" not in path.parts:
                        from_dirs.append(path.relative_to(skill.meta.skill_dir).as_posix())
        merged: list[str] = []
        for path in from_markdown + from_dirs:
            if path not in merged:
                merged.append(path)
        return merged

    def choose_resources(self, skill: LoadedSkill, request: str, *, mode: str = "auto") -> list[str]:
        if mode == "none":
            return []
        all_paths = self.available_relative_paths(skill)
        if mode == "all":
            return [p for p in all_paths if p.startswith("references/") or p.endswith((".md", ".json", ".html", ".svg", ".txt", ".css", ".js"))]
        if mode != "auto":
            raise HarnessError(f"Unknown resource loading mode: {mode}")

        chosen: list[str] = []
        request_l = request.lower()
        diagram_map = [
            (("架构", "architecture", "系统图", "组件"), "references/architecture.md"),
            (("流程", "flowchart", "process", "决策"), "references/flowchart.md"),
            (("时序", "sequence", "交互", "生命线"), "references/sequence.md"),
            (("结构", "structural", "类图", "er图", "组织架构"), "references/structural.md"),
        ]
        for triggers, path in diagram_map:
            if path in all_paths and any(t in request_l for t in triggers):
                chosen.append(path)
        html_terms = ("html", "页面", "网页", "landing", "dashboard", "report page", "static ui", "web page")
        if skill.meta.name == "html-page" or any(t in request_l for t in html_terms):
            for path in ("references/page-patterns.md", "assets/template.html"):
                if path in all_paths:
                    chosen.append(path)
        if not chosen and any(t in request_l for t in ("详细", "reference", "规范", "指南")):
            chosen.extend(p for p in all_paths if p.startswith("references/") and p.endswith(".md"))
        return _dedupe(chosen)

    def load_resource(self, skill: LoadedSkill, relative_path: str, *, max_chars: int | None = None) -> LoadedResource:
        normalized = relative_path.replace("\\", "/").lstrip("/")
        key = (skill.meta.name, normalized)
        if key in self._resource_cache:
            return self._resource_cache[key]
        path = (skill.meta.skill_dir / normalized).resolve()
        skill_root = skill.meta.skill_dir.resolve()
        if not str(path).lower().startswith(str(skill_root).lower()):
            raise HarnessError(f"Refusing to load resource outside skill dir: {relative_path}")
        if not path.exists() or not path.is_file():
            raise HarnessError(f"Resource not found: {relative_path}")
        content = read_text(path)
        if max_chars is not None and len(content) > max_chars:
            content = content[:max_chars] + "\n\n[...truncated by harness max_chars...]"
        loaded = LoadedResource(path=path, relative_path=normalized, content=content)
        self._resource_cache[key] = loaded
        self.trace.append(TraceEvent("load_resource", f"loaded {normalized}", str(path), len(content.encode("utf-8"))))
        return loaded

    def build_context(
        self,
        request: str,
        *,
        explicit_skill: str | None = None,
        resource_mode: str = "auto",
        max_resource_chars: int | None = None,
    ) -> dict[str, Any]:
        selected = self.select(request, explicit_skill=explicit_skill)
        loaded_skill = self.load_skill(selected.skill.name)
        resource_paths = self.choose_resources(loaded_skill, request, mode=resource_mode)
        resources = [self.load_resource(loaded_skill, p, max_chars=max_resource_chars) for p in resource_paths]
        return {
            "request": request,
            "selected": selected.to_dict(),
            "skill": loaded_skill,
            "resources": resources,
            "available_paths": self.available_relative_paths(loaded_skill),
            "trace": self.trace,
        }


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item not in out:
            out.append(item)
    return out
