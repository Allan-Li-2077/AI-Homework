"""Whitelisted execution boundary for local Skills."""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.skill_handlers.baoyu_diagram import BaoyuDiagramHandler
from src.skill_handlers.flash_card import FlashCardHandler
from src.skill_registry import SkillRegistry


OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "outputs" / "skills"
ALLOWED_EXTENSIONS = {".html", ".svg", ".png", ".json"}


@dataclass
class SkillExecutionResult:
    run_id: str
    skill_name: str
    success: bool
    summary: str = ""
    artifacts: list[dict] = field(default_factory=list)
    error: str = ""
    loaded_references: list[str] = field(default_factory=list)


class SkillExecutor:
    def __init__(
        self,
        registry: SkillRegistry,
        output_root: Path = OUTPUT_ROOT,
        handlers: dict | None = None,
    ):
        self.registry = registry
        self.output_root = output_root.resolve()
        self.handlers = handlers or {
            "flash-card": FlashCardHandler(),
            "baoyu-diagram": BaoyuDiagramHandler(),
        }

    def execute(
        self,
        skill_name: str,
        request: str,
        arguments: dict,
        session_id: int,
        progress: Callable[[str, str], None] | None = None,
    ) -> SkillExecutionResult:
        progress = progress or (lambda _step, _message: None)
        run_id = self._new_run_id(skill_name)
        result = SkillExecutionResult(run_id=run_id, skill_name=skill_name, success=False)
        skill = self.registry.get(skill_name)
        handler = self.handlers.get(skill_name)
        if skill is None or handler is None:
            result.error = f"Skill 未注册可执行 Handler: {skill_name}"
            return result

        run_dir = (self.output_root / str(session_id) / run_id).resolve()
        if not run_dir.is_relative_to(self.output_root):
            result.error = "Skill 产物目录越界"
            return result
        run_dir.mkdir(parents=True, exist_ok=False)

        try:
            progress("loaded", f"已加载 Skill: {skill_name}")
            handler_result = handler.execute(skill, request, arguments, run_dir, progress)
            artifacts = self._validate_artifacts(run_dir, handler_result.get("artifacts", []))
            result.success = True
            result.summary = str(handler_result.get("summary", "Skill 执行完成"))
            result.artifacts = artifacts
            result.loaded_references = list(handler_result.get("loaded_references", []))
        except Exception as exc:
            result.error = str(exc)
        return result

    def _validate_artifacts(self, run_dir: Path, artifacts: list[dict]) -> list[dict]:
        validated = []
        for artifact in artifacts:
            path = Path(artifact["path"]).resolve()
            if not path.is_relative_to(run_dir) or path.suffix.lower() not in ALLOWED_EXTENSIONS:
                raise ValueError(f"非法 Skill 产物路径: {path}")
            if not path.is_file():
                raise FileNotFoundError(f"Skill 产物不存在: {path}")
            validated.append({
                "path": str(path),
                "filename": str(artifact.get("filename") or path.name),
                "media_type": str(artifact.get("media_type") or "application/octet-stream"),
            })
        return validated

    @staticmethod
    def _new_run_id(skill_name: str) -> str:
        safe_name = re.sub(r"[^a-z0-9_-]+", "_", skill_name.lower())
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{stamp}_{safe_name}_{uuid.uuid4().hex[:8]}"
