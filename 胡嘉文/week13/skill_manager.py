"""
技能管理器 — 发现 skills/ 目录下的技能，匹配用户意图，按需加载执行

教学重点：
  1. 渐进式加载：启动只读 frontmatter，匹配到才读完整 body，执行前才读脚本
  2. 两阶段匹配：关键词打分 → 模式匹配，简单直接
  3. 与现有四层记忆系统无缝集成，追加 skill 指令到 system prompt

用法：
  sm = SkillManager("../skills")
  sm.discover()
  sm.list_skills()          # → ['baoyu-diagram', 'flash-card']
  sm.match("画个架构图")     # → ('baoyu-diagram', 2)
  sm.load("flash-card")     # → "<完整的 SKILL.md body>"
"""

import os
import re
import yaml
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── 技能元数据（只含 frontmatter，不含 body） ──────────────────────────────────

class SkillMeta:
    """一个技能的轻量元数据，discover() 时创建，不读 body"""
    def __init__(self, name: str, description: str, keywords: list[str],
                 dirpath: Path, version: str = ""):
        self.name = name
        self.description = description
        self.keywords = keywords
        self.dirpath = dirpath
        self.version = version

    def __repr__(self):
        return f"<SkillMeta {self.name}: {self.description[:30]}...>"


# ── 完整技能（body 加载后） ────────────────────────────────────────────────────

class Skill:
    """完整加载的技能，包含 body、脚本列表、数据文件"""
    def __init__(self, meta: SkillMeta):
        self.meta = meta
        self.body: str = ""               # SKILL.md body（--- 后面的内容）
        self.scripts: list[Path] = []     # scripts/ 下的可执行文件
        self.data_files: list[Path] = []  # data/ 下的文件
        self._loaded = False              # 是否已完整加载

    def load(self):
        """读完整的 SKILL.md body + 扫描 scripts/ 和 data/"""
        skill_md = self.meta.dirpath / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        # 分离 frontmatter 和 body
        parts = content.split("---", 2)
        if len(parts) >= 3:
            self.body = parts[2].strip()
        else:
            self.body = content.strip()

        # 替换 {baseDir} → 技能自己目录的路径
        self.body = self.body.replace("{baseDir}", str(self.meta.dirpath))
        self.body = self.body.replace("{projectDir}", str(self.meta.dirpath.parent))

        # 扫描 scripts/
        scripts_dir = self.meta.dirpath / "scripts"
        if scripts_dir.exists():
            self.scripts = sorted([
                f for f in scripts_dir.iterdir()
                if f.is_file() and not f.name.startswith(".")
                and f.name != "package.json" and f.name != "bun.lock"
            ])

        # 扫描 data/
        data_dir = self.meta.dirpath / "data"
        if data_dir.exists():
            self.data_files = sorted([
                f for f in data_dir.iterdir()
                if f.is_file() and not f.name.startswith(".")
            ])

        self._loaded = True
        logger.info(f"技能 [{self.meta.name}] 已加载：{len(self.body)} 字符, "
                     f"{len(self.scripts)} 个脚本, {len(self.data_files)} 个数据文件")
        return self.body

    @property
    def is_loaded(self) -> bool:
        return self._loaded


# ── 技能管理器 ─────────────────────────────────────────────────────────────────

class SkillManager:
    """
    技能管理器：发现 → 匹配 → 加载 → 获取 system prompt

    用法：
      sm = SkillManager("../skills")
      sm.discover()
      result = sm.match("帮我做 crazy 的闪卡")
      if result:
          name, score = result
          system_prompt = sm.get_system_prompt(name)
          # 注入到 LLM 的 system message
    """

    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self._registry: dict[str, SkillMeta] = {}   # name → SkillMeta
        self._cache: dict[str, Skill] = {}           # name → Skill（完整加载后）

    # ── 发现 ─────────────────────────────────────────────────────────────────

    def discover(self) -> list[str]:
        """
        扫描 skills_dir，读每个 SKILL.md 的 YAML frontmatter
        只提取 name, description, keywords, version
        不读 body — 渐进式加载
        返回发现的技能名列表
        """
        self._registry.clear()
        self._cache.clear()

        if not self.skills_dir.exists():
            logger.warning(f"技能目录不存在: {self.skills_dir}")
            return []

        for child in sorted(self.skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.exists():
                continue

            meta = self._parse_frontmatter(skill_md)
            if meta:
                self._registry[meta.name] = meta
                logger.info(f"发现技能: {meta.name}")

        return list(self._registry.keys())

    def _parse_frontmatter(self, skill_md_path: Path) -> Optional[SkillMeta]:
        """解析一个 SKILL.md 的 YAML frontmatter，返回 SkillMeta"""
        try:
            content = skill_md_path.read_text(encoding="utf-8")
            parts = content.split("---", 2)
            if len(parts) < 3:
                logger.warning(f"缺少 frontmatter: {skill_md_path}")
                return None

            frontmatter = yaml.safe_load(parts[1])

            name = frontmatter.get("name", "")
            if not name:
                logger.warning(f"SKILL.md 缺少 name: {skill_md_path}")
                return None

            description = frontmatter.get("description", "")
            keywords = frontmatter.get("keywords", [])

            # 如果没写 keywords，从 description 里抽关键词
            if not keywords:
                keywords = self._extract_keywords(description)

            version = frontmatter.get("version", "")

            return SkillMeta(
                name=name,
                description=description,
                keywords=keywords,
                dirpath=skill_md_path.parent,
                version=version,
            )
        except Exception as e:
            logger.error(f"解析 frontmatter 失败: {skill_md_path}: {e}")
            return None

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """
        从描述文本中提取中文关键词
        策略：找中文里 2-6 字的连续字符，去重
        """
        # 匹配中文连续字符
        tokens = re.findall(r'[一-鿿]{2,6}', text)
        # 去重，保持顺序
        seen = set()
        result = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result

    # ── 匹配 ─────────────────────────────────────────────────────────────────

    def match(self, user_message: str) -> Optional[tuple[str, float]]:
        """
        关键词匹配：对 user_message 分词，对每个技能打分
        返回 (技能名, 分数) 或 None（无匹配）
        """
        if not self._registry:
            self.discover()
        if not self._registry:
            return None

        best_name = None
        best_score = 0.0

        for name, meta in self._registry.items():
            score = self._score_message(user_message, meta)
            if score > best_score:
                best_score = score
                best_name = name

        if best_score > 0 and best_name:
            return (best_name, best_score)
        return None

    def _score_message(self, message: str, meta: SkillMeta) -> float:
        """
        计算消息与技能的匹配度
        规则：
          - 消息包含 keywords 中的词 → 每个 +1.0
          - 消息包含 description 中的中文关键词 → 每个 +0.5
          - 消息包含技能名 → +2.0
        """
        score = 0.0
        msg_lower = message.lower()

        # 1. 匹配技能名
        if meta.name.lower() in msg_lower:
            score += 2.0

        # 2. 匹配 keywords
        for kw in meta.keywords:
            kw = kw.lower().strip()
            if kw and kw in msg_lower:
                score += 1.0

        # 3. 匹配 description 里的中文词
        desc_keywords = self._extract_keywords(meta.description)
        for kw in desc_keywords:
            if kw in message:
                score += 0.5

        return score

    # ── 加载 ─────────────────────────────────────────────────────────────────

    def load(self, name: str) -> Optional[str]:
        """
        按技能名完整加载（读 body + 扫描 scripts/data）
        缓存调用，重复调用不重复读
        返回 SKILL.md body（已替换 {baseDir}）
        """
        if name not in self._registry:
            logger.warning(f"技能不存在: {name}")
            return None

        if name in self._cache:
            return self._cache[name].body

        skill = Skill(self._registry[name])
        body = skill.load()
        self._cache[name] = skill
        return body

    def get_system_prompt(self, name: str) -> Optional[str]:
        """
        获取技能对应的 system prompt
        = 加载 body + 拼接 references/ 内容 + 脚本说明
        """
        skill = self._get_or_load(name)
        if not skill:
            return None

        parts = [skill.body]

        # 拼接 references/
        refs_dir = skill.meta.dirpath / "references"
        if refs_dir.exists():
            for ref_file in sorted(refs_dir.iterdir()):
                if ref_file.suffix in (".md", ".txt"):
                    parts.append(f"\n## 参考文件：{ref_file.name}\n")
                    parts.append(ref_file.read_text(encoding="utf-8"))

        # 拼接脚本说明
        if skill.scripts:
            parts.append("\n## 可执行脚本\n")
            for s in skill.scripts:
                runtime = _detect_runtime(s)
                parts.append(f"- `{s.name}`（{runtime}）")

        return "\n".join(parts)

    def get_scripts(self, name: str) -> list[Path]:
        """获取技能的可执行脚本列表"""
        skill = self._get_or_load(name)
        return skill.scripts if skill else []

    def get_data_files(self, name: str) -> list[Path]:
        """获取技能的数据文件列表"""
        skill = self._get_or_load(name)
        return skill.data_files if skill else []

    def _get_or_load(self, name: str) -> Optional[Skill]:
        """获取 Skill 对象，未加载则自动加载"""
        if name not in self._registry:
            return None
        if name not in self._cache:
            self.load(name)
        return self._cache.get(name)

    # ── 工具 ─────────────────────────────────────────────────────────────────

    def list_skills(self) -> list[str]:
        """列出所有已发现的技能名"""
        return list(self._registry.keys())

    def get_meta(self, name: str) -> Optional[SkillMeta]:
        """获取技能元数据"""
        return self._registry.get(name)

    def reload(self, name: str):
        """重新加载一个技能（清除缓存）"""
        if name in self._cache:
            del self._cache[name]
        if name in self._registry:
            # 重新解析 frontmatter
            skill_md = self._registry[name].dirpath / "SKILL.md"
            meta = self._parse_frontmatter(skill_md)
            if meta:
                self._registry[name] = meta


# ── 运行时检测工具 ──────────────────────────────────────────────────────────────

def _detect_runtime(script_path: Path) -> str:
    """检测脚本运行时：读 shebang 或看扩展名"""
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line.startswith("#!"):
            # #!/usr/bin/env python3 → python3
            return first_line.split("/")[-1]
    except Exception:
        pass

    suffix_map = {
        ".py": "python",
        ".ts": "bun/ts",
        ".js": "node",
        ".sh": "bash",
        ".rb": "ruby",
    }
    return suffix_map.get(script_path.suffix, "unknown")
