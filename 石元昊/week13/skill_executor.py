"""
Skill Executor — Skill 执行引擎

教学重点：
  1. 执行流程：意图匹配 → Level 2 加载 → 构建 skill context → LLM 执行
  2. Skill 的"执行"本质上是把 SKILL.md 的指令注入 LLM context，
     让 LLM 按照指令完成任务（生成文件、运行脚本等）
  3. 脚本执行：某些 skill 需要运行外部脚本（如 Python、Bun），
     Executor 负责管理子进程并捕获输出

使用方式：
  executor = SkillExecutor(loader)
  result = executor.execute("flash-card", "帮我做 resilient 的闪卡")
"""

import subprocess
import logging
from pathlib import Path
from dataclasses import dataclass, field

from src.skill_loader import SkillLoader, LoadedSkill
from src.llm_config import get_chat_client

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Skill 执行结果"""
    skill_name: str
    success: bool
    llm_response: str = ""        # LLM 的回复文本
    script_output: str = ""       # 脚本执行的 stdout
    script_error: str = ""        # 脚本执行的 stderr
    generated_files: list[str] = field(default_factory=list)  # 生成的文件路径
    error: str = ""               # 错误信息

    def summary(self) -> str:
        if self.error:
            return f"❌ {self.skill_name} 执行失败：{self.error}"
        parts = [f"✅ {self.skill_name} 执行完成"]
        if self.generated_files:
            parts.append(f"   生成文件：{', '.join(self.generated_files)}")
        if self.script_output:
            parts.append(f"   脚本输出：{self.script_output[:200]}")
        return "\n".join(parts)


class SkillExecutor:
    """
    Skill 执行器

    使用方式：
      executor = SkillExecutor(loader)
      result = executor.execute_with_llm("baoyu-diagram", "画一个微服务架构图", conversation_history)
    """

    def __init__(self, loader: SkillLoader):
        self.loader = loader

    def execute_with_llm(
        self,
        skill_name: str,
        user_message: str,
        conversation_history: list[dict] | None = None,
        project_dir: Path | None = None,
    ) -> ExecutionResult:
        """
        完整执行流程：
          1. Level 2 加载 skill
          2. 构建 skill context（SKILL.md + references）
          3. 将 skill context 作为 system prompt 注入 LLM
          4. LLM 按照 SKILL.md 指令完成任务
        """
        result = ExecutionResult(skill_name=skill_name, success=False)

        # Step 1: Level 2 加载
        skill = self.loader.load_level2(skill_name)
        if not skill:
            result.error = f"无法加载 skill：{skill_name}"
            return result

        # Step 2: 构建 skill context
        skill_context = self.loader.build_skill_context(skill_name)
        if not skill_context:
            result.error = f"Skill {skill_name} 的内容为空"
            return result

        # 替换模板变量
        base_dir = str(skill.dir_path)
        project = str(project_dir) if project_dir else str(Path.cwd())
        skill_context = skill_context.replace("{baseDir}", base_dir)
        skill_context = skill_context.replace("{projectDir}", project)

        # Step 3: 构建 LLM 消息
        system_prompt = (
            f"你是一个 Skill 执行助手。请严格按照以下 Skill 定义来完成任务。\n\n"
            f"{skill_context}\n\n"
            f"---\n"
            f"重要规则：\n"
            f"- 严格按照 SKILL.md 中描述的流程执行\n"
            f"- 如果需要生成文件，请输出完整的文件内容\n"
            f"- 如果需要运行脚本，请给出完整的命令\n"
            f"- Skill 的 baseDir 是：{base_dir}\n"
            f"- 项目目录是：{project}\n"
        )

        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            messages.extend(conversation_history[-6:])  # 最近3轮
        messages.append({"role": "user", "content": user_message})

        # Step 4: 调用 LLM
        try:
            client, model = get_chat_client()
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
            )
            result.llm_response = resp.choices[0].message.content.strip()
            result.success = True
        except Exception as e:
            result.error = f"LLM 调用失败：{e}"
            logger.error(f"Skill {skill_name} LLM 调用失败：{e}")

        return result

    def run_script(
        self,
        skill_name: str,
        script_name: str,
        args: list[str] | None = None,
        timeout: int = 60,
    ) -> ExecutionResult:
        """
        运行 skill 的脚本文件。

        支持：
          - Python 脚本 (.py)：用 python 执行
          - TypeScript 脚本 (.ts)：用 bun 或 npx bun 执行
        """
        result = ExecutionResult(skill_name=skill_name, success=False)

        skill = self.loader.load_level2(skill_name)
        if not skill:
            result.error = f"无法加载 skill：{skill_name}"
            return result

        script_path = skill.dir_path / "scripts" / script_name
        if not script_path.exists():
            result.error = f"脚本不存在：{script_path}"
            return result

        cmd = []
        if script_path.suffix == ".py":
            cmd = ["python", str(script_path)]
        elif script_path.suffix == ".ts":
            # 优先用 bun，否则用 npx
            import shutil
            if shutil.which("bun"):
                cmd = ["bun", str(script_path)]
            else:
                cmd = ["npx", "-y", "bun", str(script_path)]
        else:
            result.error = f"不支持的脚本类型：{script_path.suffix}"
            return result

        if args:
            cmd.extend(args)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(skill.dir_path),
            )
            result.script_output = proc.stdout
            result.script_error = proc.stderr
            result.success = proc.returncode == 0
            if not result.success:
                result.error = f"脚本退出码：{proc.returncode}"
        except subprocess.TimeoutExpired:
            result.error = f"脚本超时（{timeout}s）"
        except Exception as e:
            result.error = f"脚本执行异常：{e}"

        return result
