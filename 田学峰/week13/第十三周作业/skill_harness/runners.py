from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .models import ExecutionContext, RunnerResult


class SkillRunner:
    # runner 是每个 skill 的“本地执行适配器”。
    # 有些 skill 只需要给模型提供上下文，可以不写 runner；有脚本要跑时再写。
    def can_run(self, context: ExecutionContext) -> bool:
        raise NotImplementedError

    def run(self, context: ExecutionContext) -> RunnerResult:
        raise NotImplementedError


class FlashCardRunner(SkillRunner):
    STOPWORDS = {
        "a",
        "an",
        "card",
        "flash",
        "flashcard",
        "for",
        "html",
        "make",
        "me",
        "the",
        "word",
    }

    def can_run(self, context: ExecutionContext) -> bool:
        return context.skill.metadata.name == "flash-card"

    def run(self, context: ExecutionContext) -> RunnerResult:
        word = self._extract_word(context.request)
        if not word:
            return RunnerResult(status="needs_input", message="请求里没有找到英文单词。")

        root = context.skill.metadata.root
        data_path = root / "data" / f"{word}.json"
        script_path = root / "scripts" / "make_flashcard.py"
        output_dir = Path(context.options.get("output_dir") or "outputs/skill_runs")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{word}.html"

        if not data_path.exists():
            return RunnerResult(
                status="needs_data",
                message=f"缺少数据文件: {data_path}。请先补充 JSON 数据，再重新运行。",
                artifacts={"expected_data": data_path},
            )
        if not script_path.exists():
            return RunnerResult(status="error", message=f"找不到脚本: {script_path}", returncode=1)

        # adapter 不重新实现生成逻辑，而是复用 skill 自带脚本。
        # 这样 harness 只负责调度，具体能力仍然属于 skill。
        command = [sys.executable, str(script_path), str(data_path), "-o", str(output_path)]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode != 0:
            return RunnerResult(
                status="error",
                message="Flash card 脚本执行失败。",
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
        return RunnerResult(
            status="ok",
            message=f"已为 '{word}' 生成 flash card。",
            artifacts={"html": output_path},
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    def _extract_word(self, request: str) -> str | None:
        # 从用户请求里抽第一个看起来像英文单词的词。
        # 这是 demo 级别实现，复杂场景可以交给 LLM 或更严格的解析器。
        words = [w.lower() for w in re.findall(r"\b[a-zA-Z][a-zA-Z-]{1,}\b", request)]
        for word in words:
            if word not in self.STOPWORDS:
                return word
        return None


class DiagramRunner(SkillRunner):
    def can_run(self, context: ExecutionContext) -> bool:
        return context.skill.metadata.name == "baoyu-diagram"

    def run(self, context: ExecutionContext) -> RunnerResult:
        svg_path = context.options.get("svg")
        if not svg_path:
            packet = self._write_packet(context)
            return RunnerResult(
                status="prepared",
                message="已加载图表 skill 上下文。传入 --svg 后可继续执行 PNG 转换。",
                artifacts={"packet": packet},
            )

        svg = Path(svg_path)
        if not svg.exists():
            return RunnerResult(status="error", message=f"找不到 SVG 文件: {svg}", returncode=1)

        bun_command = self._bun_command()
        if not bun_command:
            return RunnerResult(
                status="needs_runtime",
                message="当前找不到 bun 或 npx。请安装 bun，或确保 npx 可用。",
                returncode=1,
            )

        script = context.skill.metadata.root / "scripts" / "main.ts"
        output_dir = Path(context.options.get("output_dir") or svg.parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{svg.stem}@2x.png"
        command = bun_command + [str(script), str(svg), "-o", str(output_path)]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode != 0:
            return RunnerResult(
                status="error",
                message="图表转换脚本执行失败。",
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
        return RunnerResult(
            status="ok",
            message="已将 SVG 转换为 PNG。",
            artifacts={"png": output_path},
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    def _write_packet(self, context: ExecutionContext) -> Path:
        # 没有现成 SVG 时，先把已加载的 skill/context 摘要写成 packet。
        # 后续可以把 packet 交给 LLM，让它基于这些材料生成 SVG。
        output_dir = Path(context.options.get("output_dir") or "outputs/skill_runs")
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = output_dir / f"{stamp}-{context.skill.metadata.name}-packet.json"
        payload = {
            "request": context.request,
            "skill": {
                "name": context.skill.metadata.name,
                "root": str(context.skill.metadata.root),
                "skill_file": str(context.skill.metadata.skill_file),
                "token_estimate": context.skill.token_estimate,
            },
            "references": [
                {
                    "path": str(ref.path),
                    "reason": ref.reason,
                    "token_estimate": ref.token_estimate,
                }
                for ref in context.references
            ],
            "trace": context.trace,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _bun_command(self) -> list[str] | None:
        # 按 skill 说明：优先 bun；没有 bun 时尝试 npx -y bun。
        if shutil.which("bun"):
            return ["bun"]
        if shutil.which("npx"):
            return ["npx", "-y", "bun"]
        return None


class RunnerRegistry:
    def __init__(self) -> None:
        # 新增 skill adapter 时，把实例加到这个列表即可。
        self.runners: list[SkillRunner] = [FlashCardRunner(), DiagramRunner()]

    def run(self, context: ExecutionContext) -> RunnerResult:
        for runner in self.runners:
            if runner.can_run(context):
                context.trace.append(f"stage 3: 执行适配器 {runner.__class__.__name__}")
                return runner.run(context)
        return RunnerResult(
            status="prepared",
            message="这个 skill 没有注册 adapter，可把执行上下文交给模型或后续工具使用。",
        )
