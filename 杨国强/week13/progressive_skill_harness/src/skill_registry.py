"""
Skill 注册表 — Layer S0：轻量级元数据索引

教学重点：
  1. "渐进式加载"的第一步：启动时**只读每个 SKILL.md 的 frontmatter**（约 500~1500 字节）
     而不是读完整正文（可能几十 KB），让启动几乎零成本
  2. 注册表本质是 dict，键 = skill 名字，值 = SkillMeta（只含 name/desc/keywords/triggers 等元数据）
  3. 与记忆系统的"四层索引"对齐思路：
     - Layer 3a SOUL.md / 3b USER.md 是全量加载（必读）
     - Layer 4 FAISS 是按需检索
     - Skill 注册表也按需：先全量索引元数据（一次性），再按需读正文

SKILL.md 格式（YAML frontmatter + Markdown 正文）：
  ---
  name: web_search
  version: 1.0.0
  description: 联网搜索最新信息，回答关于新闻、实时数据的问题
  keywords: [搜索, search, 查一下, 网上, 联网, 新闻]
  triggers: [latest_news, real_time_query]
  execution: prompt         # prompt | code | workflow
  parameters:               # 可选：声明参数 schema，供 LLM 学会调用
    - name: query
      type: string
      required: true
      description: 搜索关键词
  ---

  # Skill 正文（仅在调用时才被读取）
  ...

使用方式：
  from src.skill_registry import SkillRegistry
  reg = SkillRegistry()
  print(reg.summary())           # 启动成本：N 个 skill，M 字节
  for s in reg.items():
      print(s.name, s.description)
"""

import os
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent.parent / "skills"

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_PARAM_LINE_RE = re.compile(r"^\s*-\s*name:\s*(\S+)")
_FIELD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")


@dataclass
class SkillParam:
    name: str
    type: str = "string"
    required: bool = False
    description: str = ""


@dataclass
class SkillMeta:
    """Skill 的轻量元数据 — 仅用于索引，不含正文"""
    name: str
    version: str
    description: str
    keywords: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    execution: str = "prompt"            # prompt | code | workflow
    parameters: list[SkillParam] = field(default_factory=list)
    source_path: str = ""                # SKILL.md 绝对路径
    body_chars: int = 0                  # 正文字符数（用于显示"该 skill 实际多大"）
    frontmatter_chars: int = 0           # frontmatter 字符数（已读取）
    tags: list[str] = field(default_factory=list)
    enabled: bool = True

    def short_desc(self, max_len: int = 60) -> str:
        """截短描述，用于提示词中节省 token"""
        if len(self.description) <= max_len:
            return self.description
        return self.description[:max_len].rstrip() + "..."


class SkillRegistry:
    """Skill 注册表 — 启动时一次性扫描所有 skills/*/SKILL.md，**只读 frontmatter**

    设计要点：
      - 单次构建后缓存在内存，避免重复扫描
      - reload() 方法强制重建（用于 /reset、文件新增时）
      - search_by_keyword() 提供粗筛能力，配合 LLM 的精筛
    """

    def __init__(self, skills_dir: Path = SKILLS_DIR):
        self.skills_dir = skills_dir
        self._index: dict[str, SkillMeta] = {}
        self._built = False

    # ── 构建 ────────────────────────────────────────────────────────────────────

    def build(self) -> "SkillRegistry":
        """扫描 skills_dir 下所有 SKILL.md，仅解析 frontmatter"""
        self._index.clear()
        if not self.skills_dir.exists():
            logger.warning(f"skills 目录不存在：{self.skills_dir}")
            self._built = True
            return self

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                meta = self._parse_front_matter(skill_md)
                if meta:
                    self._index[meta.name] = meta
            except Exception as e:
                logger.error(f"解析 {skill_md} 失败：{e}")

        self._built = True
        logger.info(f"已索引 {len(self._index)} 个 skill（仅元数据）")
        return self

    def reload(self) -> "SkillRegistry":
        """强制重建索引（新增/修改 SKILL.md 后调用）"""
        return self.build()

    def _parse_front_matter(self, path: Path) -> Optional[SkillMeta]:
        """解析 SKILL.md 的 frontmatter，返回 SkillMeta（不读正文）"""
        text = path.read_text(encoding="utf-8")
        m = _FRONT_MATTER_RE.match(text)
        if not m:
            logger.warning(f"{path.name} 缺少 frontmatter，跳过")
            return None

        fm_text = m.group(1)
        body = text[m.end():]
        fields: dict[str, str | list] = {}
        params: list[SkillParam] = []
        current_param: SkillParam | None = None

        for line in fm_text.splitlines():
            line = line.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            # 参数项（多行）
            param_m = _PARAM_LINE_RE.match(line)
            if param_m:
                if current_param:
                    params.append(current_param)
                current_param = SkillParam(name=param_m.group(1))
                # 可能在同一行附带 type: x
                rest = line[param_m.end():].strip()
                if rest:
                    fields.update(_inline_kv(rest))
                continue
            if current_param and line.lstrip().startswith("-") is False:
                # 参数的子字段（缩进）
                sub = line.strip()
                if sub.startswith("type:"):
                    current_param.type = sub.split(":", 1)[1].strip()
                elif sub.startswith("required:"):
                    current_param.required = sub.split(":", 1)[1].strip().lower() == "true"
                elif sub.startswith("description:"):
                    current_param.description = sub.split(":", 1)[1].strip()
                continue
            field_m = _FIELD_RE.match(line)
            if field_m:
                if current_param:
                    params.append(current_param)
                    current_param = None
                key, val = field_m.group(1), field_m.group(2).strip()
                # 去掉包裹引号
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                if val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                # 列表字段
                if key in ("keywords", "triggers", "tags"):
                    # 形如 [a, b, c] 的 inline 列表
                    if val.startswith("[") and val.endswith("]"):
                        inner = val[1:-1]
                        fields[key] = [s.strip().strip("'\"") for s in inner.split(",") if s.strip()]
                    else:
                        fields[key] = []
                else:
                    fields[key] = val

        if current_param:
            params.append(current_param)

        if "name" not in fields:
            logger.warning(f"{path.name} frontmatter 缺少 name 字段，跳过")
            return None

        return SkillMeta(
            name=fields["name"],
            version=fields.get("version", "0.0.0"),
            description=fields.get("description", ""),
            keywords=fields.get("keywords", []),
            triggers=fields.get("triggers", []),
            execution=fields.get("execution", "prompt"),
            parameters=params,
            source_path=str(path),
            body_chars=len(body),
            frontmatter_chars=len(fm_text),
            tags=fields.get("tags", []),
            enabled=str(fields.get("enabled", "true")).lower() != "false",
        )

    # ── 查询 ────────────────────────────────────────────────────────────────────

    def items(self) -> list[SkillMeta]:
        """返回所有 skill 的列表（替代被内置 list() 命名空间冲突的 list 方法名）"""
        return list(self._index.values())

    def get(self, name: str) -> Optional[SkillMeta]:
        return self._index.get(name)

    def names(self) -> list[str]:
        return list(self._index.keys())

    def search_by_keyword(self, query: str) -> list[SkillMeta]:
        """粗筛：匹配 description / keywords / triggers 中的任意子串"""
        q = query.lower()
        hits: list[tuple[int, SkillMeta]] = []
        for meta in self._index.values():
            if not meta.enabled:
                continue
            score = 0
            haystacks = [meta.name.lower(), meta.description.lower()]
            haystacks.extend(k.lower() for k in meta.keywords)
            haystacks.extend(t.lower() for t in meta.triggers)
            haystacks.extend(t.lower() for t in meta.tags)
            for h in haystacks:
                if q in h:
                    score += 1
            if score > 0:
                hits.append((score, meta))
        hits.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in hits]

    # ── 报告 ────────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """返回注册表加载报告，用于前端展示'启动成本'"""
        total_fm = sum(m.frontmatter_chars for m in self._index.values())
        total_body = sum(m.body_chars for m in self._index.values())
        return {
            "skill_count": len(self._index),
            "frontmatter_total_chars": total_fm,
            "body_total_chars": total_body,
            "loaded_at_build": True,
            "loaded_on_demand": True,
            "execution_modes": self._count_by("execution"),
        }

    def _count_by(self, field: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for m in self._index.values():
            v = getattr(m, field, "?")
            out[v] = out.get(v, 0) + 1
        return out


def _inline_kv(rest: str) -> dict:
    """处理 - name: foo 同行后面的 type: bar 这种"""
    out = {}
    for part in rest.split():
        if ":" in part:
            k, v = part.split(":", 1)
            out[k] = v
    return out


# ── 便捷函数 ───────────────────────────────────────────────────────────────────

_default_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    """全局单例：首次调用时构建，之后复用"""
    global _default_registry
    if _default_registry is None:
        _default_registry = SkillRegistry().build()
    return _default_registry


def reload_registry() -> SkillRegistry:
    """强制重建全局注册表"""
    global _default_registry
    _default_registry = SkillRegistry().build()
    return _default_registry