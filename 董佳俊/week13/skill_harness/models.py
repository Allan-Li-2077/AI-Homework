"""
Skill Harness 核心数据模型

教学重点：
  1. 分层数据模型：元信息(L0) → 完整定义(L1) → 引用加载(L2) → 脚本执行(L3)
  2. 每个 dataclass 职责单一，清晰反映渐进式加载的每个阶段

设计原则：
  - L0(SkillMeta): 仅含 frontmatter 信息，轻量、可快速扫描
  - L1+L2(Skill): 完整技能定义，instructions 按需加载，references 按需加载
  - MatchResult: 记录匹配过程，保留匹配类型和得分
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillMeta:
    """
    L0 产物 — 仅从 YAML frontmatter 解析的轻量元信息。

    Phase 0 启动时扫描所有 SKILL.md 文件，仅读取前 ~15 行（frontmatter 部分），
    不读取正文内容。即使有大量 skill，扫描速度也极快。
    """
    name: str                        # 技能唯一标识，如 "baoyu-diagram"
    description: str                 # 技能描述（用于匹配触发）
    version: str = ""                # 版本号（可选）
    path: Path = field(default_factory=Path)  # SKILL.md 所在目录


@dataclass
class Skill:
    """
    L1+L2 产物 — 完整技能定义（按需加载）。

    Phase 2 加载 SKILL.md 正文到 instructions
    Phase 3 按需加载 references/ 下的文件到 references dict
    Phase 4 脚本路径用于可能的执行

    未匹配的 skill 不会触发 Phase 2+ 的加载，零 I/O 开销。
    """
    meta: SkillMeta
    instructions: str = ""           # SKILL.md 去除 frontmatter 后的正文
    references: dict = field(default_factory=dict)  # {文件名: 文件内容}，初始空
    scripts: list = field(default_factory=list)     # [Path, ...] 可用脚本列表


@dataclass
class MatchResult:
    """
    Phase 1 产物 — 用户输入与 skill 的匹配结果。

    记录匹配得分、类型，供上层决策是否触发 Phase 2 加载。
    """
    skill: Skill = None
    score: float = 0.0              # 匹配得分 0.0~1.0
    match_type: str = ""            # "command" | "keyword" | "llm"
    matched_keywords: list = field(default_factory=list)  # 命中的关键词
