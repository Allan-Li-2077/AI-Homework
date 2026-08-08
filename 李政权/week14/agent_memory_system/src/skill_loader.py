"""
Skill 能力层 — 按需加载的专项工作流说明书

教学重点：
  1. Skill = 带 YAML frontmatter 的 SKILL.md（对齐 Cursor Agent Skills 格式）
  2. 渐进披露：目录只注入 name+description；命中后再注入全文，节省 Context
  3. 匹配策略：显式调用（/skill、@name）优先；否则按描述关键词打分自动激活

目录约定：
  skills/
    <skill-name>/
      SKILL.md          # 必需
      reference.md      # 可选，正文可链接，本模块按需读取一级引用

使用方式：
  from src.skill_loader import SkillLoader
  loader = SkillLoader()
  matched = loader.match("帮我写今日站会", top_k=2)
  block = loader.format_for_prompt(matched)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "skills"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_EXPLICIT_RE = re.compile(
    r"(?:/skill\s+|@skill\s+|@)([a-z0-9][a-z0-9\-_]{0,63})",
    re.IGNORECASE,
)
_CJK_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,}")
_ASCII_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9\-_]{2,}")


@dataclass
class SkillMeta:
    name: str
    description: str
    path: Path
    disable_model_invocation: bool = False
    body: str = ""
    char_count: int = 0

    def to_catalog_line(self) -> str:
        flag = "（仅显式调用）" if self.disable_model_invocation else ""
        return f"- **{self.name}**{flag}：{self.description}"


@dataclass
class SkillMatchResult:
    catalog: list[SkillMeta]
    activated: list[SkillMeta] = field(default_factory=list)
    match_reasons: dict[str, str] = field(default_factory=dict)

    @property
    def catalog_chars(self) -> int:
        return sum(len(s.to_catalog_line()) for s in self.catalog)

    @property
    def activated_chars(self) -> int:
        return sum(s.char_count for s in self.activated)


class SkillLoader:
    def __init__(self, skills_dir: Path = SKILLS_DIR):
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    # ── 扫描 ──────────────────────────────────────────────────────────────────

    def list_skills(self) -> list[SkillMeta]:
        skills: list[SkillMeta] = []
        if not self.skills_dir.exists():
            return skills
        for skill_md in sorted(self.skills_dir.glob("*/SKILL.md")):
            meta = self._parse_skill_md(skill_md, load_body=False)
            if meta:
                skills.append(meta)
        return skills

    def get_skill(self, name: str, load_body: bool = True) -> SkillMeta | None:
        name = name.strip().lower()
        path = self.skills_dir / name / "SKILL.md"
        if not path.exists():
            # 也允许目录名与 frontmatter name 不一致时按 frontmatter 查找
            for meta in self.list_skills():
                if meta.name == name:
                    return self._parse_skill_md(meta.path, load_body=load_body)
            return None
        return self._parse_skill_md(path, load_body=load_body)

    # ── 匹配 ──────────────────────────────────────────────────────────────────

    def match(self, query: str, top_k: int = 2) -> SkillMatchResult:
        """
        显式调用优先；否则对可自动激活的 skill 做关键词打分，取 Top-K。
        """
        catalog = self.list_skills()
        result = SkillMatchResult(catalog=catalog)
        if not catalog or not query.strip():
            return result

        activated: list[SkillMeta] = []
        reasons: dict[str, str] = {}

        # 1) 显式：/skill foo 或 @foo
        for name in _EXPLICIT_RE.findall(query):
            meta = self.get_skill(name, load_body=True)
            if meta and meta.name not in reasons:
                activated.append(meta)
                reasons[meta.name] = "explicit"
                # 展开一级引用（若正文链到同目录 md）
                self._hydrate_references(meta)

        # 2) 自动：描述/名称关键词打分
        if len(activated) < top_k:
            scored: list[tuple[float, SkillMeta, str]] = []
            tokens = self._tokenize(query)
            for meta in catalog:
                if meta.disable_model_invocation:
                    continue
                if meta.name in reasons:
                    continue
                score, why = self._score(meta, query, tokens)
                if score > 0:
                    scored.append((score, meta, why))
            scored.sort(key=lambda x: x[0], reverse=True)
            for score, meta, why in scored:
                if len(activated) >= top_k:
                    break
                full = self.get_skill(meta.name, load_body=True)
                if not full:
                    continue
                self._hydrate_references(full)
                activated.append(full)
                reasons[full.name] = f"auto:{why}({score:.2f})"

        result.activated = activated
        result.match_reasons = reasons
        return result

    # ── Prompt 组装 ───────────────────────────────────────────────────────────

    def format_for_prompt(self, match: SkillMatchResult) -> str:
        """生成注入 System Prompt 的 Skill 区块（目录 + 已激活全文）。"""
        parts: list[str] = []

        if match.catalog:
            lines = ["## 可用 Skills（按需能力）", ""]
            lines.append(
                "以下是专项工作流目录。仅当用户意图匹配时遵循对应 Skill 的完整说明；"
                "用户也可通过 `/skill <name>` 或 `@<name>` 显式调用。"
            )
            lines.append("")
            for s in match.catalog:
                lines.append(s.to_catalog_line())
            parts.append("\n".join(lines))

        if match.activated:
            blocks = ["## 已激活 Skills", ""]
            for s in match.activated:
                reason = match.match_reasons.get(s.name, "")
                blocks.append(f"### Skill: {s.name}")
                if reason:
                    blocks.append(f"激活原因：{reason}")
                blocks.append("")
                blocks.append(s.body.strip())
                blocks.append("")
            parts.append("\n".join(blocks).strip())

        return "\n\n---\n\n".join(parts)

    def layers_info(self, match: SkillMatchResult) -> list[dict]:
        """供 SSE / CLI 展示的加载明细。"""
        info = [{
            "name": "skill_catalog",
            "source": "skills/*/SKILL.md",
            "chars": match.catalog_chars,
            "count": len(match.catalog),
        }]
        for s in match.activated:
            info.append({
                "name": f"skill:{s.name}",
                "source": str(s.path.relative_to(self.skills_dir.parent)).replace("\\", "/"),
                "chars": s.char_count,
                "reason": match.match_reasons.get(s.name, ""),
            })
        return info

    # ── 内部 ──────────────────────────────────────────────────────────────────

    def _parse_skill_md(self, path: Path, load_body: bool) -> SkillMeta | None:
        raw = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(raw)
        if not m:
            # 无 frontmatter：用目录名兜底
            name = path.parent.name
            body = raw if load_body else ""
            return SkillMeta(
                name=name,
                description=f"Skill at {path.parent.name}",
                path=path,
                body=body,
                char_count=len(body),
            )

        fm_text, body = m.group(1), m.group(2)
        fields = self._parse_frontmatter(fm_text)
        name = (fields.get("name") or path.parent.name).strip().lower()
        description = (fields.get("description") or "").strip()
        if not description:
            description = f"Skill: {name}"
        disable = str(fields.get("disable-model-invocation", "false")).lower() in (
            "true", "1", "yes",
        )
        body = body if load_body else ""
        return SkillMeta(
            name=name,
            description=description,
            path=path,
            disable_model_invocation=disable,
            body=body,
            char_count=len(body),
        )

    @staticmethod
    def _parse_frontmatter(text: str) -> dict[str, str]:
        """简易 YAML 子集：只解析 key: value 单行（description 可多行用 >- 折叠为单行文本）。"""
        fields: dict[str, str] = {}
        current_key = None
        buf: list[str] = []

        def flush():
            nonlocal current_key, buf
            if current_key is not None:
                fields[current_key] = " ".join(buf).strip().strip("\"'")
            current_key, buf = None, []

        for line in text.splitlines():
            if re.match(r"^[a-zA-Z0-9_-]+\s*:", line) and not line.startswith(" "):
                flush()
                key, _, val = line.partition(":")
                current_key = key.strip()
                val = val.strip()
                if val in (">", ">-", "|", "|-"):
                    buf = []
                elif val:
                    buf = [val]
                else:
                    buf = []
            elif current_key is not None:
                buf.append(line.strip())
        flush()
        return fields

    def _hydrate_references(self, skill: SkillMeta):
        """读取 SKILL.md 中同目录一级 md 链接，追加到 body（渐进披露）。"""
        if not skill.body:
            return
        links = re.findall(r"\[([^\]]+)\]\(([^)]+\.md)\)", skill.body)
        extras: list[str] = []
        for _label, rel in links:
            if "/" in rel.replace("\\", "/").lstrip("./"):
                # 只允许同目录一级
                continue
            ref_path = skill.path.parent / rel
            if ref_path.exists() and ref_path.is_file():
                extras.append(
                    f"\n\n---\n### 参考：{rel}\n\n{ref_path.read_text(encoding='utf-8').strip()}"
                )
        if extras:
            skill.body = skill.body.rstrip() + "".join(extras)
            skill.char_count = len(skill.body)

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        tokens = set()
        for t in _CJK_TOKEN.findall(text):
            tokens.add(t)
            # 也加入 2-gram 子串增强中文召回
            if len(t) >= 4:
                for i in range(len(t) - 1):
                    tokens.add(t[i:i + 2])
        for t in _ASCII_TOKEN.findall(text.lower()):
            tokens.add(t)
        return tokens

    def _score(self, meta: SkillMeta, query: str, tokens: set[str]) -> tuple[float, str]:
        q = query.lower()
        # 名称直接出现
        name_variants = {
            meta.name,
            meta.name.replace("-", " "),
            meta.name.replace("-", ""),
        }
        if any(v and v in q for v in name_variants):
            return 10.0, "name"

        # 描述里的中文触发短语（≥2 字连续）在 query 中直接命中 → 高分
        desc = meta.description
        phrase_hits = []
        for phrase in _CJK_TOKEN.findall(desc):
            if len(phrase) >= 2 and phrase in query:
                phrase_hits.append(phrase)
            # 也检查描述短语的 2-gram 是否出现在 query
            if len(phrase) >= 4:
                for i in range(len(phrase) - 1):
                    bi = phrase[i:i + 2]
                    if bi in query:
                        phrase_hits.append(bi)
        phrase_hits = list(dict.fromkeys(phrase_hits))  # 去重保序
        if phrase_hits:
            # 长短语加权更高
            best = max(len(p) for p in phrase_hits)
            score = 3.0 + best * 0.8 + len(phrase_hits) * 0.3
            return score, "phrase:" + ",".join(phrase_hits[:5])

        desc_tokens = self._tokenize(desc + " " + meta.name.replace("-", " "))
        if not desc_tokens or not tokens:
            return 0.0, ""

        overlap = tokens & desc_tokens
        if not overlap:
            return 0.0, ""

        score = len(overlap) / max(len(desc_tokens), 1) * 5 + len(overlap) * 0.8
        if score < 0.6:
            return 0.0, ""
        return score, "keywords:" + ",".join(sorted(overlap)[:5])
