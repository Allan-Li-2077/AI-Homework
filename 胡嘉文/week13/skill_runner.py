"""
脚本执行器 — 安全运行技能关联的脚本（子进程）

教学重点：
  1. 自动检测运行时（Python/Bun/Bash/Node）
  2. 超时保护，防止脚本卡死
  3. 错误不崩溃，优雅降级

用法：
  import asyncio
  result = await run_script("scripts/make_flashcard.py",
                              args=["data/crazy.json", "-o", "crazy.html"])
  print(result.stdout)       # 脚本输出
  print(result.return_code)  # 0 = 成功
"""

import os
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ScriptResult:
    """脚本执行结果"""
    script_name: str
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    error: Optional[str] = None
    output_files: list[Path] = field(default_factory=list)


async def run_script(
    script_path: Path,
    args: Optional[list[str]] = None,
    cwd: Optional[Path] = None,
    timeout: int = 120,
    extra_env: Optional[dict[str, str]] = None,
) -> ScriptResult:
    """
    安全执行一个脚本

    参数：
      script_path — 脚本文件路径
      args        — 命令行参数列表
      cwd         — 工作目录（默认脚本所在目录）
      timeout     — 超时秒数（默认 120s）
      extra_env   — 额外环境变量

    返回：
      ScriptResult（永远不抛异常 — 错误在 result 里）
    """
    script_path = Path(script_path).resolve()
    if not script_path.exists():
        return ScriptResult(
            script_name=script_path.name,
            return_code=-1,
            stdout="",
            stderr="",
            error=f"脚本不存在: {script_path}",
        )

    # 确定运行时
    runtime = _detect_runtime(script_path)
    if runtime == "unknown":
        return ScriptResult(
            script_name=script_path.name,
            return_code=-1,
            stdout="",
            stderr="",
            error=f"无法识别脚本类型: {script_path}（支持 .py .ts .js .sh）",
        )

    # cwd 默认脚本所在目录
    if cwd is None:
        cwd = script_path.parent

    # 构建命令
    cmd = [runtime, str(script_path)]
    if args:
        cmd.extend(args)

    # 环境变量：继承当前 PATH，加额外变量
    env = os.environ.copy()
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env["PYTHONUNBUFFERED"] = "1"
    if extra_env:
        env.update(extra_env)

    logger.info(f"运行脚本: {' '.join(cmd)} (cwd={cwd}, timeout={timeout}s)")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            timed_out = False
        except asyncio.TimeoutError:
            proc.kill()
            stdout, stderr = await proc.communicate()
            timed_out = True
            logger.warning(f"脚本超时 ({timeout}s): {script_path.name}")

        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        # 收集输出文件：扫描 cwd 下，修改时间在脚本运行期间的新文件
        # 简单的做法：返回脚本打印的文件路径信息
        output_files = _extract_file_paths(stdout_str, cwd)

        return ScriptResult(
            script_name=script_path.name,
            return_code=proc.returncode or 0,
            stdout=stdout_str,
            stderr=stderr_str,
            timed_out=timed_out,
            output_files=output_files,
        )

    except FileNotFoundError:
        return ScriptResult(
            script_name=script_path.name,
            return_code=-1,
            stdout="",
            stderr="",
            error=f"找不到运行时 '{runtime}'。请安装: {runtime}",
        )
    except Exception as e:
        logger.exception(f"脚本执行异常: {script_path}")
        return ScriptResult(
            script_name=script_path.name,
            return_code=-1,
            stdout="",
            stderr="",
            error=str(e),
        )


def _detect_runtime(script_path: Path) -> str:
    """检测脚本运行时：优先读 shebang，再看扩展名"""
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line.startswith("#!"):
            # #!/usr/bin/env python3 → python3
            return first_line.split("/")[-1]
    except Exception:
        pass

    suffix_map = {
        ".py": "python3",
        ".ts": "bun",
        ".js": "node",
        ".sh": "bash",
    }
    return suffix_map.get(script_path.suffix, "unknown")


def _extract_file_paths(text: str, base_dir: Path) -> list[Path]:
    """从脚本输出中提取文件路径（简单启发式）"""
    paths = []
    for line in text.split("\n"):
        line = line.strip()
        # 找看起来像路径的内容：以 ./ 或 / 开头，或者包含 .html .svg .png .json
        for token in line.split():
            if "/" in token or "\\" in token:
                token = token.strip("'\"()[],。")
                p = Path(token)
                if p.suffix in (".html", ".svg", ".png", ".json", ".txt", ".md"):
                    if not p.is_absolute():
                        p = base_dir / p
                    if p.exists():
                        paths.append(p)
    return paths
