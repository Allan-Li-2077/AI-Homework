"""
SkillExecutor - Skill流程执行引擎

渐进式加载第四阶段:
- 按SKILL.md定义的执行流程逐步执行
- 每一步可产生进度事件
- 支持不同类型的动作（读取、生成、运行脚本等）

教学重点:
1. 步骤化执行与进度反馈
2. 脚本执行（subprocess）
3. 文件操作
4. 错误处理与回滚
"""

import os
import re
import json
import time
import logging
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable
from datetime import datetime

from .skill_loader import SkillContent, SkillStep
from .skill_registry import SkillMeta

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """单步执行结果"""
    step_index: int
    description: str
    success: bool = True
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class ExecutionResult:
    """Skill执行结果"""
    skill_name: str
    success: bool = False
    started_at: float = 0.0
    completed_at: float = 0.0
    total_duration_ms: float = 0.0
    steps: list[StepResult] = field(default_factory=list)
    final_output: str = ""
    errors: list[str] = field(default_factory=list)
    
    @property
    def step_count(self) -> int:
        return len(self.steps)
    
    @property
    def success_count(self) -> int:
        return sum(1 for s in self.steps if s.success)
    
    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.steps if not s.success)
    
    @property
    def has_warnings(self) -> bool:
        return self.failed_count > 0


class SkillExecutor:
    """
    Skill执行引擎
    
    根据SkillContent中解析的执行流程逐步执行，
    每一步产生StepResult并可触发进度回调。
    """
    
    def __init__(
        self,
        work_dir: Optional[str | Path] = None,
        on_step_start: Optional[Callable[[int, str], None]] = None,
        on_step_complete: Optional[Callable[[int, StepResult], None]] = None,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ):
        self.work_dir = Path(work_dir) if work_dir else Path.cwd()
        self.on_step_start = on_step_start
        self.on_step_complete = on_step_complete
        self.on_progress = on_progress
        self._execution_count = 0
    
    def execute(
        self,
        content: SkillContent,
        user_input: str = "",
        params: Optional[dict] = None,
    ) -> ExecutionResult:
        """
        执行Skill的完整流程
        
        渐进式执行:
        1. 解析SKILL.md中的执行流程
        2. 逐步执行每个步骤
        3. 每步产生进度事件
        4. 汇总结果
        """
        import time
        
        result = ExecutionResult(
            skill_name=content.name,
            started_at=time.time(),
        )
        
        logger.info(f"开始执行Skill: {content.name}")
        logger.info(f"用户输入: {user_input[:100]}")
        
        # 准备参数
        params = params or {}
        params["user_input"] = user_input
        params["skill_name"] = content.name
        params["work_dir"] = str(self.work_dir)
        params["skill_dir"] = str(content.skill_dir)
        
        try:
            # 加载必要的资源
            self._prepare_resources(content, params)
            
            # 获取执行流程
            steps = content.execution_flow
            if not steps:
                # 如果没有解析到流程，使用默认流程
                steps = self._generate_default_flow(content, user_input)
            
            logger.info(f"执行流程共 {len(steps)} 步")
            
            # 逐步执行
            for i, step in enumerate(steps):
                step_start = time.time()
                
                # 触发步骤开始回调
                if self.on_step_start:
                    self.on_step_start(step.index, step.description)
                
                # 触发进度回调
                progress = (i / len(steps)) * 100
                if self.on_progress:
                    self.on_progress(progress, f"执行步骤 {i+1}/{len(steps)}: {step.description[:50]}")
                
                # 执行步骤
                step_result = self._execute_step(step, content, params)
                step_result.duration_ms = (time.time() - step_start) * 1000
                result.steps.append(step_result)
                
                # 触发步骤完成回调
                if self.on_step_complete:
                    self.on_step_complete(step.index, step_result)
                
                # 步骤失败处理
                if not step_result.success and not step.is_optional:
                    result.errors.append(step_result.error)
                    logger.error(f"步骤 {step.index} 失败: {step_result.error}")
                    # 非可选步骤失败，停止执行
                    break
            
            # 先设置success状态，再生成输出
            result.success = result.failed_count == 0
            
            # 生成最终输出
            result.final_output = self._generate_output(content, result, params)
            
        except Exception as e:
            logger.error(f"执行异常: {e}", exc_info=True)
            result.errors.append(str(e))
            result.success = False
        
        result.completed_at = time.time()
        result.total_duration_ms = (result.completed_at - result.started_at) * 1000
        self._execution_count += 1
        
        # 完成进度
        if self.on_progress:
            self.on_progress(100.0, f"执行完成: {'成功' if result.success else '失败'}")
        
        status = "成功" if result.success else "失败"
        logger.info(
            f"Skill执行{status}: {content.name} "
            f"({result.success_count}/{result.step_count}步, "
            f"{result.total_duration_ms:.0f}ms)"
        )
        
        return result
    
    def _prepare_resources(self, content: SkillContent, params: dict):
        """准备执行所需的资源"""
        # 如果skill有scripts，加载它们
        if content.meta.has_scripts:
            if not content._scripts:
                content._scripts = []
                scripts_dir = content.skill_dir / "scripts"
                for f in sorted(scripts_dir.iterdir()):
                    if f.is_file():
                        try:
                            text = f.read_text(encoding="utf-8")
                            content._scripts.append((f.name, text))
                        except Exception:
                            pass
        
        # 如果skill有data目录，加载数据文件
        if content.meta.has_data:
            if not content._data_files:
                content._data_files = []
                data_dir = content.skill_dir / "data"
                for f in sorted(data_dir.iterdir()):
                    if f.is_file():
                        try:
                            text = f.read_text(encoding="utf-8")
                            content._data_files.append((f.name, text))
                        except Exception:
                            pass
        
        logger.debug(f"资源准备完成: {len(content._scripts)} scripts, {len(content._data_files)} data files")
    
    def _execute_step(
        self,
        step: SkillStep,
        content: SkillContent,
        params: dict,
    ) -> StepResult:
        """执行单个步骤"""
        step_result = StepResult(
            step_index=step.index,
            description=step.description,
        )
        
        action = step.action_type
        
        try:
            if action == "read_file":
                step_result = self._action_read_file(step, content, params)
            elif action == "generate":
                step_result = self._action_generate(step, content, params)
            elif action == "write_file":
                step_result = self._action_write_file(step, content, params)
            elif action == "run_command":
                step_result = self._action_run_command(step, content, params)
            else:
                step_result = self._action_default(step, content, params)
        except Exception as e:
            step_result.success = False
            step_result.error = str(e)
            step_result.output = f"执行异常: {e}"
        
        return step_result
    
    def _action_read_file(
        self,
        step: SkillStep,
        content: SkillContent,
        params: dict,
    ) -> StepResult:
        """读取文件动作"""
        # 尝试读取相关文件
        output_parts = []
        
        # 读取SKILL.md中的references
        refs_dir = content.skill_dir / "references"
        if refs_dir.is_dir():
            for f in sorted(refs_dir.iterdir())[:3]:  # 最多读取3个参考文件
                if f.is_file():
                    try:
                        text = f.read_text(encoding="utf-8")
                        output_parts.append(f"  - {f.name}: {len(text)} 字符")
                    except Exception:
                        pass
        
        # 读取SKILL.md本身
        if content.intro_text:
            output_parts.append(f"  - SKILL.md 正文: {len(content.intro_text)} 字符")
        
        return StepResult(
            step_index=step.index,
            description=step.description,
            success=True,
            output="\n".join(output_parts) if output_parts else "（无参考文件需要加载）",
        )
    
    def _action_generate(
        self,
        step: SkillStep,
        content: SkillContent,
        params: dict,
    ) -> StepResult:
        """生成内容动作"""
        user_input = params.get("user_input", "")
        
        # 从用户输入中提取关键参数
        extracted = self._extract_params(user_input, content)
        
        # 生成示例输出
        output = self._generate_content(content, extracted, params)
        
        return StepResult(
            step_index=step.index,
            description=step.description,
            success=True,
            output=output,
        )
    
    def _action_write_file(
        self,
        step: SkillStep,
        content: SkillContent,
        params: dict,
    ) -> StepResult:
        """写入文件动作"""
        work_dir = Path(params.get("work_dir", self.work_dir))
        skill_name = content.meta.name
        
        # 确保输出目录存在
        output_dir = work_dir / "outputs" / skill_name
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成输出路径
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"{skill_name}_{timestamp}.txt"
        
        # 生成内容
        output_content = self._generate_output_content(content, params)
        
        # 写入文件
        output_file.write_text(output_content, encoding="utf-8")
        
        return StepResult(
            step_index=step.index,
            description=step.description,
            success=True,
            output=f"文件已保存: {output_file}",
        )
    
    def _action_run_command(
        self,
        step: SkillStep,
        content: SkillContent,
        params: dict,
    ) -> StepResult:
        """运行命令/脚本动作"""
        user_input = params.get("user_input", "")
        
        # 查找可用的脚本
        script_files = content.meta.get_script_files()
        
        if not script_files:
            return StepResult(
                step_index=step.index,
                description=step.description,
                success=True,
                output="（无可用脚本，跳过执行）",
            )
        
        # 执行第一个脚本（简化处理）
        script = script_files[0]
        
        # 构建命令（智能参数处理）
        cmd = self._build_command(script, content, params)
        
        try:
            # 运行命令
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.work_dir,
                timeout=30,
            )
            
            success = result.returncode == 0
            output = result.stdout.strip() or result.stderr.strip()
            
            return StepResult(
                step_index=step.index,
                description=step.description,
                success=success,
                output=output[:500] if output else f"命令执行完成: {'成功' if success else '失败'}",
                error=result.stderr if not success else "",
            )
        except subprocess.TimeoutExpired:
            return StepResult(
                step_index=step.index,
                description=step.description,
                success=False,
                output="命令执行超时（30秒）",
                error="TimeoutExpired",
            )
        except Exception as e:
            return StepResult(
                step_index=step.index,
                description=step.description,
                success=False,
                output=f"命令执行失败: {e}",
                error=str(e),
            )
    
    def _action_default(
        self,
        step: SkillStep,
        content: SkillContent,
        params: dict,
    ) -> StepResult:
        """默认动作（文本描述）"""
        return StepResult(
            step_index=step.index,
            description=step.description,
            success=True,
            output=f"步骤描述: {step.description}",
        )
    
    def _build_command(
        self,
        script_path: Path,
        content: SkillContent,
        params: dict,
    ) -> list[str]:
        """构建执行命令（智能参数处理）"""
        suffix = script_path.suffix.lower()
        
        if suffix == ".py":
            cmd = ["python", str(script_path)]
        elif suffix in (".ts", ".js"):
            cmd = ["bun", "run", str(script_path)]
        elif suffix == ".sh":
            cmd = ["bash", str(script_path)]
        elif suffix == ".bat":
            cmd = [str(script_path)]
        else:
            cmd = [str(script_path)]
        
        # 智能参数处理
        user_input = params.get("user_input", "")
        
        # 检查是否有可用的数据文件
        data_dir = content.skill_dir / "data"
        if data_dir.is_dir():
            # 尝试根据用户输入提取关键词来匹配数据文件
            extracted = self._extract_params(user_input, content)
            word = extracted.get("word", "")
            
            # 优先使用与提取的单词匹配的 JSON 文件
            if word:
                json_file = data_dir / f"{word}.json"
                if json_file.exists():
                    cmd.append(str(json_file))
                    return cmd
            
            # 如果没有匹配的，使用第一个可用的 JSON 文件
            json_files = sorted(data_dir.glob("*.json"))
            if json_files:
                cmd.append(str(json_files[0]))
                return cmd
        
        # 如果没有数据文件，使用用户输入作为参数
        if user_input:
            cmd.append(user_input)
        
        return cmd
    
    def _extract_params(self, user_input: str, content: SkillContent) -> dict:
        """从用户输入中提取参数"""
        params = {"raw_input": user_input}
        
        # 简单提取引号内容
        quoted = re.findall(r'[""「](.+?)[""」]', user_input)
        if quoted:
            params["quoted"] = quoted[0]
        
        # 提取可能的目标对象
        skill_name = content.meta.name
        
        if "flash" in skill_name.lower():
            # 提取单词
            words = re.findall(r'[a-zA-Z]+', user_input)
            if words:
                params["word"] = words[0]
        elif "diagram" in skill_name.lower():
            # 提取图表类型
            diagram_types = ["架构图", "流程图", "时序图", "结构图", "mind map", "timeline"]
            for dt in diagram_types:
                if dt.lower() in user_input.lower():
                    params["diagram_type"] = dt
                    break
        
        return params
    
    def _generate_content(self, content: SkillContent, extracted: dict, params: dict) -> str:
        """生成执行内容描述"""
        parts = []
        user_input = params.get("user_input", "")
        
        if "word" in extracted:
            parts.append(f"目标单词: {extracted['word']}")
        if "diagram_type" in extracted:
            parts.append(f"图表类型: {extracted['diagram_type']}")
        
        if not parts:
            # 通用描述
            parts.append(f"处理输入: {user_input[:50]}")
            parts.append(f"Skill: {content.meta.name} v{content.meta.version}")
        
        return "执行参数:\n" + "\n".join(f"  - {p}" for p in parts)
    
    def _generate_output_content(self, content: SkillContent, params: dict) -> str:
        """生成输出文件内容"""
        user_input = params.get("user_input", "")
        skill_name = content.meta.name
        timestamp = datetime.now().isoformat()
        
        lines = [
            f"# Skill Execution Output",
            f"",
            f"- **Skill**: {skill_name}",
            f"- **Version**: {content.meta.version}",
            f"- **Time**: {timestamp}",
            f"- **Input**: {user_input}",
            f"",
        ]
        
        if content.trigger_scenarios:
            lines.append("## 触发场景")
            for scenario in content.trigger_scenarios:
                lines.append(f"- {scenario}")
            lines.append("")
        
        if content.execution_flow:
            lines.append("## 执行流程")
            for step in content.execution_flow:
                lines.append(f"{step.index}. {step.description}")
            lines.append("")
        
        if content.notes:
            lines.append("## 注意事项")
            for note in content.notes:
                lines.append(f"- {note}")
            lines.append("")
        
        return "\n".join(lines)
    
    def _generate_default_flow(
        self,
        content: SkillContent,
        user_input: str,
    ) -> list[SkillStep]:
        """生成默认执行流程"""
        steps = []
        
        # Step 1: 识别和理解
        steps.append(SkillStep(
            index=1,
            description=f"识别用户意图: 分析输入 '{user_input[:30]}...'，匹配skill '{content.name}'",
            action_type="text",
        ))
        
        # Step 2: 加载资源
        steps.append(SkillStep(
            index=2,
            description=f"加载Skill资源: SKILL.md, scripts/, references/",
            action_type="read_file",
        ))
        
        # Step 3: 准备数据
        steps.append(SkillStep(
            index=3,
            description="准备执行数据: 从用户输入中提取关键参数",
            action_type="generate",
        ))
        
        # Step 4: 执行核心逻辑
        if content.meta.has_scripts:
            steps.append(SkillStep(
                index=4,
                description=f"执行脚本: 运行 {len(content.meta.get_script_files())} 个脚本",
                action_type="run_command",
            ))
        else:
            steps.append(SkillStep(
                index=4,
                description="执行核心逻辑: 按SKILL.md描述的流程处理",
                action_type="generate",
            ))
        
        # Step 5: 输出结果
        steps.append(SkillStep(
            index=5,
            description="生成输出: 保存执行结果并展示给用户",
            action_type="write_file",
        ))
        
        return steps
    
    def _generate_output(
        self,
        content: SkillContent,
        result: ExecutionResult,
        params: dict,
    ) -> str:
        """生成最终输出"""
        parts = []
        
        # 标题
        parts.append(f"## Skill执行结果: {content.name}")
        parts.append("")
        
        # 状态
        status = "✅ 成功" if result.success else "❌ 失败"
        parts.append(f"**状态**: {status}")
        parts.append(f"**耗时**: {result.total_duration_ms:.0f}ms")
        parts.append(f"**步骤**: {result.success_count}/{result.step_count}")
        parts.append("")
        
        # 步骤详情
        parts.append("### 步骤详情")
        for step in result.steps:
            icon = "✅" if step.success else "❌"
            parts.append(f"{icon} **Step {step.step_index}**: {step.description[:60]}")
            if step.output and step.output != step.description:
                parts.append(f"   ```\n   {step.output[:200]}\n   ```")
        
        # 错误信息
        if result.errors:
            parts.append("")
            parts.append("### 错误信息")
            for err in result.errors:
                parts.append(f"- {err}")
        
        return "\n".join(parts)
    
    @property
    def execution_count(self) -> int:
        """累计执行次数"""
        return self._execution_count
