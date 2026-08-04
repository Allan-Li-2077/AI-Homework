"""
配置管理模块

负责管理 Harness 的全局配置，包括：
- Skill 扫描目录路径
- 日志级别
- 匹配阈值
- 其他运行时参数
"""

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class HarnessConfig:
    """Harness 运行时配置"""

    # Skill 目录路径（支持多个目录）
    skill_dirs: list[Path] = field(default_factory=lambda: [Path("skills")])

    # 匹配阈值：低于此分数的 Skill 不会被触发（0~1）
    match_threshold: float = 0.3

    # 最大返回匹配结果数
    max_matches: int = 3

    # 日志级别
    log_level: str = "INFO"

    # 是否启用渐进式加载（True=按需加载，False=启动时全量加载）
    lazy_loading: bool = True

    # 默认超时时间（秒）
    default_timeout: int = 30

    @classmethod
    def from_env(cls) -> "HarnessConfig":
        """从环境变量读取配置"""
        config = cls()

        # SKILL_DIRS 环境变量：逗号分隔的目录路径
        if dirs := os.getenv("SKILL_DIRS"):
            config.skill_dirs = [Path(d.strip()) for d in dirs.split(",")]

        # 匹配阈值
        if threshold := os.getenv("MATCH_THRESHOLD"):
            config.match_threshold = float(threshold)

        # 日志级别
        if level := os.getenv("LOG_LEVEL"):
            config.log_level = level

        # 是否启用渐进式加载
        if lazy := os.getenv("LAZY_LOADING"):
            config.lazy_loading = lazy.lower() in ("true", "1", "yes")

        return config

    def resolve_skill_dirs(self, base_dir: Path | None = None) -> list[Path]:
        """
        解析 Skill 目录的绝对路径

        Args:
            base_dir: 基准目录，默认使用当前工作目录

        Returns:
            绝对路径列表
        """
        base = base_dir or Path.cwd()
        resolved = []
        for d in self.skill_dirs:
            if d.is_absolute():
                resolved.append(d)
            else:
                resolved.append(base / d)
        return resolved
