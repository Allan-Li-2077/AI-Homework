"""
Harness - Skill 编排框架核心

负责 Skill 的完整生命周期管理：
1. 初始化：配置加载、Skill 发现
2. 匹配：根据用户输入找到最合适的 Skill
3. 执行：渐进式加载并执行 Skill
4. 监控：记录执行日志和状态
"""

import logging
from pathlib import Path
from typing import Optional

from config import HarnessConfig
from skill_loader import SkillLoader, SkillMeta
from skill_matcher import SkillMatcher, MatchResult
from skill_executor import SkillExecutor, ExecutionResult

logger = logging.getLogger(__name__)


class Harness:
    """
    Skill Harness 主类

    渐进式加载执行流程：
    1. 启动时：扫描目录 → 解析所有 SKILL.md 的元数据（轻量）
    2. 匹配时：根据输入找到最佳 Skill（只操作元数据）
    3. 执行时：完整加载 Skill 内容 → 执行脚本（按需重载）

    这种设计确保：
    - 启动快速（不加载脚本内容）
    - 内存高效（只加载用到的 Skill）
    - 响应及时（元数据匹配速度快）
    """

    def __init__(self, config: Optional[HarnessConfig] = None):
        self.config = config or HarnessConfig.from_env()
        self.loader = SkillLoader()
        self.matcher = SkillMatcher(threshold=self.config.match_threshold)
        self.executor = SkillExecutor(default_timeout=self.config.default_timeout)

        self._initialized = False
        self._base_dir: Path = Path.cwd()

    def init(self, base_dir: Optional[Path] = None) -> "Harness":
        """
        初始化 Harness：发现并加载所有 Skill 元数据

        Args:
            base_dir: 基准目录，默认当前工作目录

        Returns:
            self（支持链式调用）
        """
        self._base_dir = base_dir or Path.cwd()
        skill_dirs = self.config.resolve_skill_dirs(self._base_dir)

        logger.info(f"Harness 初始化中... 扫描目录: {skill_dirs}")
        self.loader.discover(skill_dirs)
        self._initialized = True

        skills = self.loader.list_skills()
        logger.info(f"Harness 初始化完成，共加载 {len(skills)} 个 Skill")
        for skill in skills:
            logger.info(f"  - {skill.name}: {skill.description[:50]}...")

        return self

    def process(self, user_input: str) -> Optional[ExecutionResult]:
        """
        处理用户输入：匹配 → 加载 → 执行

        Args:
            user_input: 用户输入文本

        Returns:
            执行结果，如果没有匹配的 Skill 则返回 None
        """
        if not self._initialized:
            raise RuntimeError("Harness 未初始化，请先调用 init()")

        logger.info(f"处理输入: {user_input}")

        # 1. 匹配 Skill
        matches = self.matcher.match(user_input, self.loader.list_skills())
        if not matches:
            logger.info("没有匹配的 Skill")
            return None

        # 2. 选择最佳匹配
        best_match = matches[0]
        logger.info(
            f"最佳匹配: {best_match.skill.name} "
            f"(分数: {best_match.score}, 类型: {best_match.match_type})"
        )

        # 打印其他候选（调试用）
        for m in matches[1:]:
            logger.debug(f"  候选: {m.skill.name} (分数: {m.score})")

        # 3. 渐进式加载：完整加载 Skill 内容
        skill = self.loader.load_full(best_match.skill.name)
        if not skill:
            return ExecutionResult(
                success=False,
                error_message=f"Skill '{best_match.skill.name}' 加载失败",
            )

        # 4. 执行 Skill
        # 将用户输入作为参数传递给脚本
        result = self.executor.execute(skill, args=[user_input])

        if result.success:
            logger.info(f"Skill '{skill.name}' 执行成功")
        else:
            logger.error(f"Skill '{skill.name}' 执行失败: {result.error_message}")

        return result

    def list_skills(self) -> list[SkillMeta]:
        """列出所有已发现的 Skill"""
        return self.loader.list_skills()

    def reload(self) -> "Harness":
        """重新加载所有 Skill"""
        skill_dirs = self.config.resolve_skill_dirs(self._base_dir)
        self.loader.reload(skill_dirs)
        logger.info("Skill 列表已重新加载")
        return self

    def get_skill_info(self, name: str) -> Optional[dict]:
        """获取 Skill 详细信息"""
        skill = self.loader.get_skill(name)
        if not skill:
            return None

        return {
            "name": skill.name,
            "description": skill.description,
            "version": skill.version,
            "triggers": skill.triggers,
            "script": skill.script,
            "script_type": skill.script_type,
            "working_dir": str(skill.working_dir),
            "loaded": skill._content_loaded,
        }
