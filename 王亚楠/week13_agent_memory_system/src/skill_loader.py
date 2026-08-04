"""
Skill 加载器 — 技能发现、匹配与注入

教学重点：
  1. Skill 是 Layer 3 的动态扩展：Markdown 文件定义可复用能力模块
  2. 两级匹配策略：关键词初筛（零成本）→ LLM 语义匹配（兜底）
  3. 与 HEARTBEAT 体系一致的设计模式：正则 + LLM 双重判断

使用方式：
  from src.skill_loader import SkillLoader
  loader = SkillLoader()
  skills = loader.list_skills()
  matched = loader.match("帮我审查这段代码")  # → SkillMatch 或 None

依赖：无外部依赖（LLM 调用走 llm_config）
"""

import re
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from src.llm_config import get_chat_client

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent.parent / "skills"
SKILLS_INDEX = Path(__file__).parent.parent / "memory" / "SKILLS.md"


@dataclass
class SkillDef:
    """单个技能的定义"""
    name: str           # 唯一标识，如 "code-reviewer"
    display_name: str   # 显示名，如 "代码审查"
    description: str    # 一句话描述
    triggers: list[str] # 触发关键词列表
    category: str       # 分组，如 "开发"
    file_path: Path     # 技能 .md 文件路径
    content: str = ""   # 技能的 Instructions 内容（system prompt 注入用）

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "triggers": self.triggers,
            "category": self.category,
        }


@dataclass
class SkillMatch:
    """一次技能匹配的结果"""
    skill: SkillDef
    method: str  # "keyword" | "llm" | "explicit"
    confidence: float  # 0.0 ~ 1.0


# ── 显式调用 pattern ──────────────────────────────────────────────────────────
EXPLICIT_PATTERN = re.compile(
    r'^/(?:skill|技能)\s+(\S+)|使用(?:技能)?[：:]*\s*(\S+)'
)


_SKILL_MATCH_PROMPT = """\
你是一个技能匹配助手。用户的输入可能适合使用某个特定的技能来处理。

当前可用技能：
{skill_list}

用户输入："{message}"

判断用户输入是否适合使用上述某个技能。如果匹配，返回：
{{"matched": true, "skill": "技能名", "confidence": 0.0~1.0}}

如果不匹配任何技能，返回：
{{"matched": false}}

只返回 JSON，不要有其他文字。"""


class SkillLoader:
    def __init__(self, skills_dir: Path = SKILLS_DIR, index_path: Path = SKILLS_INDEX):
        self.skills_dir = skills_dir
        self.index_path = index_path
        self._skills: list[SkillDef] = []
        self._loaded = False

    def _ensure_loaded(self):
        """懒加载：首次调用时从 skills/ 目录加载所有技能"""
        if self._loaded:
            return
        self._skills = self._discover_skills()
        self._loaded = True

    def _discover_skills(self) -> list[SkillDef]:
        """从 skills/ 目录扫描所有 .md 文件，解析元信息"""
        skills = []
        if not self.skills_dir.exists():
            logger.warning(f"技能目录不存在：{self.skills_dir}")
            return skills

        for md_file in sorted(self.skills_dir.glob("*.md")):
            try:
                skill = self._parse_skill_file(md_file)
                if skill:
                    skills.append(skill)
            except Exception as e:
                logger.warning(f"解析技能文件失败 {md_file.name}：{e}")

        logger.info(f"已加载 {len(skills)} 个技能：{[s.name for s in skills]}")
        return skills

    def _parse_skill_file(self, file_path: Path) -> SkillDef | None:
        """解析单个技能 .md 文件"""
        text = file_path.read_text(encoding="utf-8")
        lines = text.splitlines()

        name = file_path.stem  # 默认用文件名
        display_name = name
        description = ""
        triggers = []
        category = "通用"
        in_instructions = False
        instructions_lines = []

        for line in lines:
            if line.startswith("# Skill:"):
                display_name = line.replace("# Skill:", "").strip()
            elif line.startswith("description:"):
                description = line.replace("description:", "").strip()
            elif line.startswith("triggers:"):
                triggers_str = line.replace("triggers:", "").strip()
                triggers = [t.strip() for t in triggers_str.split(",") if t.strip()]
            elif line.startswith("category:"):
                category = line.replace("category:", "").strip()
            elif line.startswith("## Instructions"):
                in_instructions = True
            elif in_instructions:
                instructions_lines.append(line)

        if not description:
            return None  # description 是必填字段

        instructions = "\n".join(instructions_lines).strip()

        return SkillDef(
            name=name,
            display_name=display_name,
            description=description,
            triggers=triggers,
            category=category,
            file_path=file_path,
            content=instructions,
        )

    # ── 公共 API ──────────────────────────────────────────────────────────────

    def list_skills(self) -> list[SkillDef]:
        """返回所有已注册技能"""
        self._ensure_loaded()
        return list(self._skills)

    def get_skill(self, name: str) -> SkillDef | None:
        """按名称查找技能"""
        self._ensure_loaded()
        for s in self._skills:
            if s.name == name:
                return s
        return None

    def match(self, message: str, use_llm: bool = True) -> SkillMatch | None:
        """
        两级匹配：关键词 → LLM（可选）

        返回 SkillMatch 或 None（不匹配任何技能）。
        """
        self._ensure_loaded()
        if not self._skills:
            return None

        # Tier 0: 显式调用
        explicit = self._match_explicit(message)
        if explicit:
            return explicit

        # Tier 1: 关键词匹配
        keyword = self._match_keyword(message)
        if keyword:
            return keyword

        # Tier 2: LLM 语义匹配
        if use_llm:
            return self._match_llm(message)

        return None

    def match_explicit_only(self, message: str) -> SkillDef | None:
        """仅检查显式调用（/skill name 或 使用XX技能），用于命令处理"""
        self._ensure_loaded()
        m = EXPLICIT_PATTERN.search(message)
        if m:
            name = m.group(1) or m.group(2)
            if name:
                return self.get_skill(name.strip())
        return None

    def match_keyword_only(self, message: str) -> SkillMatch | None:
        """仅关键词匹配，不调 LLM"""
        self._ensure_loaded()
        return self._match_keyword(message)

    # ── 内部实现 ─────────────────────────────────────────────────────────────

    def _match_explicit(self, message: str) -> SkillMatch | None:
        """检测 /skill <name> 或 使用XX技能"""
        m = EXPLICIT_PATTERN.search(message)
        if not m:
            return None
        name = m.group(1) or m.group(2)
        if not name:
            return None
        skill = self.get_skill(name.strip())
        if skill:
            return SkillMatch(skill=skill, method="explicit", confidence=1.0)
        return None

    def _match_keyword(self, message: str) -> SkillMatch | None:
        """关键词匹配：检查 message 是否包含任何技能的 triggers 关键词"""
        best: tuple[SkillDef, int, int] | None = None  # skill, total triggers, longest match len

        for skill in self._skills:
            match_count = 0
            max_len = 0
            for trigger in skill.triggers:
                if trigger.lower() in message.lower():
                    match_count += 1
                    max_len = max(max_len, len(trigger))
            if match_count > 0:
                # 按命中数 + 最长匹配长度排序，取最佳
                if best is None or (match_count > best[1] or (match_count == best[1] and max_len > best[2])):
                    best = (skill, match_count, max_len)

        if best:
            # confidence 基于命中关键词数（粗略估算）
            confidence = min(0.9, 0.5 + best[1] * 0.2)
            return SkillMatch(skill=best[0], method="keyword", confidence=confidence)

        return None

    def _match_llm(self, message: str) -> SkillMatch | None:
        """LLM 语义匹配：让模型判断消息最适合哪个技能"""
        self._ensure_loaded()
        if not self._skills:
            return None

        skill_list = "\n".join(
            f"- {s.name}（{s.display_name}）：{s.description}"
            for s in self._skills
        )
        prompt = _SKILL_MATCH_PROMPT.format(skill_list=skill_list, message=message)

        try:
            client, model = get_chat_client()
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            raw = resp.choices[0].message.content.strip()
            data = self._parse_json_safe(raw)
            if not data or not data.get("matched"):
                return None
            skill_name = data.get("skill", "").strip()
            skill = self.get_skill(skill_name)
            if not skill:
                return None
            confidence = float(data.get("confidence", 0.5))
            return SkillMatch(skill=skill, method="llm", confidence=confidence)
        except Exception as e:
            logger.warning(f"LLM 技能匹配失败：{e}")
            return None

    @staticmethod
    def _parse_json_safe(text: str) -> dict | None:
        """容错 JSON 解析（与 heartbeat_parser 一致）"""
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
        text = re.sub(r"\n?```$", "", text.strip())
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return None
