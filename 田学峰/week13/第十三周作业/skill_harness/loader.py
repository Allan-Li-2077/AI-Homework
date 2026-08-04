from __future__ import annotations

import re
from pathlib import Path

from .frontmatter import read_text
from .models import ExecutionContext, LoadedReference, LoadedSkill, SkillMetadata


REFERENCE_MAP = {
    "architecture.md": ("architecture", "架构", "系统", "network", "topology"),
    "flowchart.md": ("flowchart", "流程", "决策", "步骤", "process"),
    "sequence.md": ("sequence", "时序", "交互", "调用", "message"),
    "structural.md": ("structural", "结构", "类图", "er", "关系"),
}


class ProgressiveLoader:
    def load_skill(self, metadata: SkillMetadata) -> LoadedSkill:
        # 只有 matcher 选中某个 skill 后，才加载完整 SKILL.md。
        return LoadedSkill(metadata=metadata, content=read_text(metadata.skill_file))

    def load_references(
        self,
        loaded_skill: LoadedSkill,
        request: str,
        *,
        load_all: bool = False,
    ) -> list[LoadedReference]:
        refs_dir = loaded_skill.metadata.root / "references"
        if not refs_dir.exists():
            return []

        # 提示：reference 文件相当于 skill 的“附录/教材”。
        # 比如画架构图只加载 architecture.md，不会把 flowchart.md 也塞进来。
        request_l = request.lower()
        selected: list[tuple[Path, str]] = []
        if load_all:
            selected = [(p, "用户显式传入 --load-all-refs") for p in sorted(refs_dir.glob("*.md"))]
        else:
            for filename, keywords in REFERENCE_MAP.items():
                if any(keyword in request_l for keyword in keywords):
                    path = refs_dir / filename
                    if path.exists():
                        selected.append((path, f"请求内容匹配到 {filename}"))

        if not selected:
            # 如果用户请求里没有明显关键词，就退一步：读取 SKILL.md 里明确提到的第一个 reference。
            selected = self._explicit_references(loaded_skill, refs_dir)

        return [
            LoadedReference(path=path, content=read_text(path), reason=reason)
            for path, reason in selected
        ]

    def build_context(
        self,
        request: str,
        metadata: SkillMetadata,
        *,
        load_all_refs: bool = False,
    ) -> ExecutionContext:
        loaded_skill = self.load_skill(metadata)
        references = self.load_references(loaded_skill, request, load_all=load_all_refs)
        trace = [
            f"stage 1: 已加载 SKILL.md ({len(loaded_skill.content)} chars, 约 {loaded_skill.token_estimate} tokens)"
        ]
        for ref in references:
            trace.append(
                f"stage 2: 已加载引用 {ref.path.relative_to(metadata.root)} "
                f"({len(ref.content)} chars, 约 {ref.token_estimate} tokens)，原因：{ref.reason}"
            )
        if not references:
            trace.append("stage 2: 未加载引用文件")
        return ExecutionContext(request=request, skill=loaded_skill, references=references, trace=trace)

    def _explicit_references(self, loaded_skill: LoadedSkill, refs_dir: Path) -> list[tuple[Path, str]]:
        matches = re.findall(r"references/([A-Za-z0-9_.-]+\.md)", loaded_skill.content)
        selected: list[tuple[Path, str]] = []
        for filename in dict.fromkeys(matches):
            path = refs_dir / filename
            if path.exists():
                selected.append((path, "SKILL.md 中明确提到"))
        return selected[:1]
