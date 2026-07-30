from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def estimate_tokens(text: str) -> int:
    # 粗略估算 token 数：英文/符号场景下 4 个字符约等于 1 个 token。
    # 这里只用于教学展示“上下文大概加载了多少”，不是计费级别的精确计算。
    return max(1, len(text) // 4) if text else 0


@dataclass(frozen=True)
class SkillMetadata:
    # 轻量元数据：只来自 frontmatter，不包含完整 SKILL.md 正文。
    name: str
    description: str
    root: Path
    skill_file: Path
    version: str | None = None
    frontmatter_chars: int = 0


@dataclass
class LoadedSkill:
    # 被真正选中后，才会把完整 SKILL.md 放到这个对象里。
    metadata: SkillMetadata
    content: str

    @property
    def token_estimate(self) -> int:
        return estimate_tokens(self.content)


@dataclass
class LoadedReference:
    # references/*.md 通常更长，所以只有请求确实需要时才加载。
    path: Path
    content: str
    reason: str

    @property
    def token_estimate(self) -> int:
        return estimate_tokens(self.content)


@dataclass
class ExecutionContext:
    # 执行上下文是 runner 真正干活时拿到的“材料包”。
    # 它包含：用户请求、完整 skill、按需引用文件、产物路径和加载轨迹。
    request: str
    skill: LoadedSkill
    references: list[LoadedReference] = field(default_factory=list)
    artifacts: dict[str, Path] = field(default_factory=dict)
    trace: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def total_token_estimate(self) -> int:
        return self.skill.token_estimate + sum(r.token_estimate for r in self.references)


@dataclass(frozen=True)
class MatchResult:
    # 匹配结果：score 越高，表示越可能应该使用这个 skill。
    skill: SkillMetadata
    score: float
    reasons: tuple[str, ...] = ()


@dataclass
class RunnerResult:
    # runner 的统一返回格式，方便 CLI 打印，也方便后续接入 Web/API。
    status: str
    message: str
    artifacts: dict[str, Path] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
