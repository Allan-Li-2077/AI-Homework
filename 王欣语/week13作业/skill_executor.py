"""
脚本执行引擎

负责：
1. 根据 Skill 的脚本类型选择执行方式
2. 调用外部脚本并传递参数
3. 捕获输出和错误
4. 超时控制
"""

import os
import sys
import shlex
import logging
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from skill_loader import SkillMeta

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """执行结果"""

    success: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    error_message: str = ""


class SkillExecutor:
    """
    Skill 执行引擎

    支持多种脚本类型：
    - python: 直接调用 Python 解释器
    - typescript: 调用 bun 或 npx tsx
    - javascript: 调用 node
    - shell: 调用 bash/sh
    """

    def __init__(self, default_timeout: int = 30):
        self.default_timeout = default_timeout

    def execute(self, skill: SkillMeta, args: list[str] | None = None) -> ExecutionResult:
        """
        执行 Skill 脚本

        Args:
            skill: 要执行的 Skill（需已完整加载）
            args: 传递给脚本的参数列表

        Returns:
            执行结果
        """
        if not skill.script:
            return ExecutionResult(
                success=False,
                error_message=f"Skill '{skill.name}' 未配置脚本路径",
            )

        script_path = Path(skill.script)
        if not script_path.exists():
            # 尝试相对路径（相对于 Skill 目录）
            script_path = skill.working_dir / skill.script
            if not script_path.exists():
                return ExecutionResult(
                    success=False,
                    error_message=f"脚本文件不存在: {skill.script}",
                )

        # 构建命令
        cmd = self._build_command(skill.script_type, str(script_path), args or [])
        logger.info(f"执行 Skill '{skill.name}': {' '.join(cmd)}")

        # 设置环境变量
        env = os.environ.copy()
        env["SKILL_NAME"] = skill.name
        env["SKILL_DIR"] = str(skill.working_dir)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.default_timeout,
                cwd=str(skill.working_dir),
                env=env,
            )

            success = result.returncode == 0
            return ExecutionResult(
                success=success,
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
                returncode=result.returncode,
                error_message=result.stderr.strip() if not success else "",
            )

        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False,
                error_message=f"执行超时（>{self.default_timeout}秒）",
            )
        except FileNotFoundError as e:
            return ExecutionResult(
                success=False,
                error_message=f"找不到执行程序: {e}",
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                error_message=f"执行异常: {e}",
            )

    def _build_command(
        self, script_type: str, script_path: str, args: list[str]
    ) -> list[str]:
        """
        根据脚本类型构建执行命令

        Args:
            script_type: 脚本类型
            script_path: 脚本路径
            args: 参数列表

        Returns:
            命令列表
        """
        cmd: list[str] = []

        if script_type == "python":
            python = sys.executable
            cmd = [python, script_path]
        elif script_type == "typescript":
            # 优先使用 bun，其次 npx tsx
            if self._which("bun"):
                cmd = ["bun", "run", script_path]
            elif self._which("npx"):
                cmd = ["npx", "-y", "tsx", script_path]
            else:
                cmd = ["node", script_path]
        elif script_type == "javascript":
            cmd = ["node", script_path]
        elif script_type == "shell":
            cmd = ["bash", script_path]
        else:
            # 未知类型，尝试直接执行
            cmd = [script_path]

        # 添加参数
        cmd.extend(args)
        return cmd

    def _which(self, program: str) -> Optional[str]:
        """检查程序是否存在"""
        return shutil.which(program)


# 延迟导入 shutil（避免循环导入）
import shutil
