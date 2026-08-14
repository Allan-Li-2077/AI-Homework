"""
Skill 加载器 — Layer S2：按需读取 SKILL.md 正文，组装"调用契约"

教学重点：
  1. **按需读取**：只有当 SkillSelector 决定调用某个 skill 时，才读 SKILL.md 全文
  2. **占位符替换**：skill 正文里可写 `{{query}}`、`{{language}}` 等占位符，由 loader 填实参
  3. **缓存**：同一会话内同一 skill 只读一次（避免重复 IO）
  4. **调用契约**：返回 SkillContract，正文 + 解析后的参数 + 元数据 + LLM 调用模板

使用方式：
  from src.skill_loader import SkillLoader
  loader = SkillLoader(registry)
  contract = loader.load("web_search", params={"query": "今天天气"})
  print(contract.prompt_for_llm)   # 填好占位符、可直接发给 LLM 的正文
"""

import re
import logging
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from src.skill_registry import SkillRegistry, SkillMeta, SKILLS_DIR

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class SkillContract:
    """Skill 的完整调用契约 — 加载后的完整数据"""
    meta: SkillMeta
    body_md: str                              # 原始 Markdown 正文
    prompt_for_llm: str                       # 填好占位符的正文（可直接作为 system message 片段）
    params_resolved: dict = field(default_factory=dict)
    params_missing: list[str] = field(default_factory=list)
    load_time_ms: float = 0.0                 # 本次加载耗时（仅首次实际读取时记录）
    cache_hit: bool = False
    content_hash: str = ""                    # 正文 hash，便于追溯


class SkillLoader:
    """按需加载 SKILL.md 正文 + 参数替换 + 缓存

    设计要点：
      - 缓存键 = (skill_name, session_id 或 'global')
      - 缓存命中直接返回 SkillContract（cache_hit=True）
      - 占位符 `{{name}}` 按 params 字典替换，未提供则记录到 params_missing
    """

    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self._cache: dict[str, SkillContract] = {}

    def load(
        self,
        skill_name: str,
        params: Optional[dict] = None,
        use_cache: bool = True,
    ) -> Optional[SkillContract]:
        """加载一个 skill 的完整调用契约"""
        params = params or {}
        cache_key = f"{skill_name}::{hashlib.md5(str(sorted(params.items())).encode()).hexdigest()[:8]}"

        if use_cache and cache_key in self._cache:
            contract = self._cache[cache_key]
            contract.cache_hit = True
            return contract

        meta = self.registry.get(skill_name)
        if not meta:
            logger.warning(f"Skill '{skill_name}' 不在注册表中")
            return None
        if not meta.enabled:
            logger.warning(f"Skill '{skill_name}' 已禁用")
            return None

        import time
        t0 = time.perf_counter()
        try:
            text = Path(meta.source_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.error(f"找不到 SKILL.md：{meta.source_path}")
            return None

        # 剥离 frontmatter（registry 已解析，这里只取正文）
        m = _FRONTMATTER_RE.match(text)
        body = text[m.end():] if m else text

        # 占位符替换
        resolved, missing = self._fill_placeholders(body, params, meta)

        # 计算正文 hash
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]

        contract = SkillContract(
            meta=meta,
            body_md=body,
            prompt_for_llm=resolved,
            params_resolved=params,
            params_missing=missing,
            cache_hit=False,
            content_hash=content_hash,
            load_time_ms=(time.perf_counter() - t0) * 1000,
        )
        self._cache[cache_key] = contract
        logger.info(
            f"按需加载 skill '{skill_name}': "
            f"{len(body)} 字符, {contract.load_time_ms:.2f}ms, hash={content_hash}"
        )
        return contract

    def invalidate(self, skill_name: Optional[str] = None):
        """清空缓存；skill_name=None 清全部"""
        if skill_name is None:
            self._cache.clear()
        else:
            keys = [k for k in self._cache if k.startswith(f"{skill_name}::")]
            for k in keys:
                self._cache.pop(k, None)

    # ── 辅助 ──────────────────────────────────────────────────────────────────

    def _fill_placeholders(
        self, body: str, params: dict, meta: SkillMeta
    ) -> tuple[str, list[str]]:
        """替换 `{{key}}` 占位符，返回 (替换后文本, 缺失参数列表)"""
        missing: list[str] = []

        def _replace(m: re.Match) -> str:
            key = m.group(1)
            if key in params:
                return str(params[key])
            # 检查 declared param 是否有默认值
            declared = next((p for p in meta.parameters if p.name == key), None)
            if declared and not declared.required:
                return f"({key}: 未提供)"
            missing.append(key)
            return f"<<{key}: MISSING>>"

        resolved = _PLACEHOLDER_RE.sub(_replace, body)
        return resolved, missing

    # ── 报告 ──────────────────────────────────────────────────────────────────

    def cache_report(self) -> dict:
        """当前缓存状态，用于调试"""
        return {
            "cached_skills": sorted({k.split("::")[0] for k in self._cache}),
            "total_entries": len(self._cache),
        }