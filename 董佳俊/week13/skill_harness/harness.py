"""
Skill Harness — 渐进式加载执行引擎（主编排器）

教学重点：
  1. 串联 L0 注册 → L1 匹配 → L2 加载 → L3 注入 → 执行的完整流水线
  2. 每个阶段独立、可观测（日志/耗时统计）
  3. 未匹配的 skill 零开销（不会触发 L2+ 加载）

使用方式：
    harness = SkillHarness(skills_dirs=[Path("./skills")])
    harness.startup()                            # L0: 启动扫描
    result = harness.process("画个架构图")         # 完整流水线
    # 或者分步调用:
    matches = harness.matcher.match("画个图")
    skill = harness.loader.load_skill(matches[0].skill.meta)
    context = harness.build_context(skill, user_input)
"""

import time
import logging
from pathlib import Path

from .models import SkillMeta, Skill, MatchResult
from .registry import SkillRegistry
from .loader import SkillLoader
from .matcher import SkillMatcher

logger = logging.getLogger(__name__)

# 默认 Skill 搜索目录
DEFAULT_SKILLS_DIRS = [
    Path(__file__).parent.parent / "skills",
]


class SkillHarness:
    """
    渐进式加载技能执行引擎（门面模式）。

    对外暴露简单的 process() 方法，内部串联：
      L0: SkillRegistry.discover()
      L1: SkillMatcher.match()
      L2: SkillLoader.load_skill()
      L3: SkillLoader.load_reference() [按需]
      注入: build_context()
      执行: run_with_llm()
    """

    def __init__(self, skills_dirs: list[Path] = None):
        """
        Args:
            skills_dirs: Skill 目录列表，默认使用项目内的 skills/ 目录
        """
        self.skills_dirs = skills_dirs or DEFAULT_SKILLS_DIRS
        self.registry = SkillRegistry()
        self.loader = SkillLoader()
        self.matcher = SkillMatcher(self.registry)

        # 统计信息
        self._phase_timings: dict[str, float] = {}
        self._total_io_bytes: int = 0       # 累计 I/O 字节数（用于对比全量加载）

    # ── L0: 启动 ────────────────────────────────────────────────────

    def startup(self) -> int:
        """
        L0: 扫描技能目录，构建注册表。

        仅读取 SKILL.md 的 frontmatter，不加载正文。
        这是 harness 的初始化入口，应在处理任何请求前调用。

        Returns:
            发现的技能数量
        """
        t0 = time.perf_counter()
        count = self.registry.discover(self.skills_dirs)
        self._phase_timings["L0_discover"] = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(
            f"[Harness] L0 启动完成: 发现 {count} 个技能 "
            f"({self._phase_timings['L0_discover']}ms)"
        )
        return count

    # ── 完整流水线 ──────────────────────────────────────────────────

    def process(
        self,
        user_input: str,
        match_strategy: str = "auto",
        match_top_k: int = 3,
    ) -> dict:
        """
        完整流水线：用户输入 → 匹配 → 加载 → 组装上下文。

        Args:
            user_input: 用户输入文本
            match_strategy: 匹配策略 ("auto" | "command" | "keyword" | "llm")
            match_top_k: 最多返回 K 个匹配

        Returns:
            {
                "matches": list[MatchResult],     # 匹配结果
                "loaded_skills": list[Skill],      # 已加载的 Skill
                "context": str,                    # 组装后的上下文
                "phase_timings": dict,             # 各阶段耗时(ms)
                "total_io_kb": float,              # 累计 I/O (KB)
            }
        """
        result = {
            "matches": [],
            "loaded_skills": [],
            "context": "",
            "phase_timings": {},
            "total_io_kb": 0,
        }

        # L1: 匹配
        t1 = time.perf_counter()
        matches = self.matcher.match(user_input, top_k=match_top_k, strategy=match_strategy)
        result["phase_timings"]["L1_match"] = round((time.perf_counter() - t1) * 1000, 2)
        result["matches"] = matches

        if not matches:
            result["context"] = f"用户输入: {user_input}\n(未匹配到技能)"
            return result

        # L2: 渐进加载（仅加载匹配到的 skill）
        t2 = time.perf_counter()
        loaded_skills = []
        for m in matches:
            # 仅对 score >= 阈值的 skill 触发 L2 加载
            if m.score >= 0.2:
                skill = self.loader.load_skill(m.skill.meta)
                m.skill = skill  # 更新 MatchResult 的 skill 引用
                loaded_skills.append(skill)
            else:
                logger.info(f"[Harness] 跳过低分匹配: {m.skill.meta.name} (score={m.score})")
        result["phase_timings"]["L2_load"] = round((time.perf_counter() - t2) * 1000, 2)
        result["loaded_skills"] = loaded_skills

        # 组装上下文
        t3 = time.perf_counter()
        result["context"] = self.build_context(loaded_skills, user_input, matches)
        result["phase_timings"]["context_build"] = round((time.perf_counter() - t3) * 1000, 2)

        # 统计
        result["total_io_kb"] = round(self._total_io_bytes / 1024, 2)

        return result

    # ── 上下文组装 ──────────────────────────────────────────────────

    def build_context(
        self,
        loaded_skills: list[Skill],
        user_input: str,
        matches: list[MatchResult] = None,
    ) -> str:
        """
        将匹配到的 Skill 指令组装为可注入 LLM 的上下文文本。

        格式：
          ## 用户请求
          {user_input}

          ## 激活的技能: {skill_name}
          {skill instructions}

          可用参考文件: [列表]
          可用脚本: [列表]
        """
        parts = [f"## 用户请求\n{user_input}\n"]

        if matches:
            match_info = "\n".join(
                f"- **{m.skill.meta.name}** (匹配类型: {m.match_type}, 得分: {m.score:.2f})"
                for m in matches
            )
            parts.append(f"## 匹配结果\n{match_info}\n")

        for skill in loaded_skills:
            parts.append(f"## 激活的技能: {skill.meta.name}")
            if skill.meta.version:
                parts.append(f"版本: {skill.meta.version}")
            parts.append(f"描述: {skill.meta.description}\n")

            if skill.instructions:
                # 限制注入长度以控制 token 消耗
                max_chars = 6000
                instr = skill.instructions
                if len(instr) > max_chars:
                    instr = instr[:max_chars] + "\n\n[...指令过长，已截断...]"
                parts.append(f"### 技能指令\n{instr}\n")

            if skill.references:
                ref_names = list(skill.references.keys())
                parts.append(f"### 可用参考文件\n" + "\n".join(f"- {n}" for n in ref_names))
                parts.append("(参考文件内容按需加载，仅在明确引用时读取)\n")

            if skill.scripts:
                script_names = [s.name for s in skill.scripts]
                parts.append(f"### 可用脚本\n" + "\n".join(f"- {n}" for n in script_names))
                parts.append("(脚本按需执行，仅在 AI 决定调用时运行)\n")

        return "\n".join(parts)

    # ── LLM 执行 ────────────────────────────────────────────────────

    def run_with_llm(self, context: str) -> str:
        """
        使用 LLM 执行技能上下文，生成回答。

        Args:
            context: build_context() 生成的上下文

        Returns:
            LLM 生成的回答文本
        """
        try:
            from .llm_config import get_chat_client
            client, model = get_chat_client()
        except (ImportError, EnvironmentError) as e:
            logger.warning(f"[Harness] LLM 不可用: {e}")
            return f"[LLM 不可用: {e}]\n\n上下文已组装，可手动查看:\n{context[:500]}..."

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个具有技能执行能力的 AI 助手。根据提供的技能指令完成用户请求。"},
                    {"role": "user", "content": context},
                ],
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"[Harness] LLM 调用失败: {e}")
            return f"[LLM 调用失败: {e}]"

    # ── L3: 按需加载参考 ────────────────────────────────────────────

    def load_reference(self, skill_name: str, ref_name: str) -> str | None:
        """
        L3: 按需加载参考文件。

        当 skill 指令中提到"→ 阅读 references/xxx.md"时调用。
        """
        skill = self.loader._cache.get(skill_name)
        if not skill:
            logger.warning(f"[Harness] 技能 '{skill_name}' 未加载，无法读取参考")
            return None

        return self.loader.load_reference(skill, ref_name)

    # ── 工具方法 ────────────────────────────────────────────────────

    def get_skill_list(self) -> list[dict]:
        """获取技能摘要列表（用于 CLI 展示）"""
        return [
            {
                "name": meta.name,
                "description": meta.description[:80],
                "version": meta.version,
            }
            for meta in self.registry.list_skills()
        ]

    def get_stats(self) -> dict:
        """获取 harness 运行统计"""
        loader_stats = self.loader.stats()
        return {
            "discovered_skills": self.registry.skill_count,
            "loaded_skills": loader_stats["cached_skills"],
            "references_loaded": loader_stats["total_references_loaded"],
            "phase_timings": self._phase_timings,
            "total_io_kb": round(self._total_io_bytes / 1024, 2),
            "cached_skill_names": loader_stats["cached_names"],
        }
