"""
Stage 2: Context Building & Injection (上下文构建与注入)

职责：
  1. 解析 skill 依赖关系
  2. 收集前置 skill 的执行结果
  3. 构建执行上下文（Context Window）
  4. 参数验证与类型检查

设计理念（与 week13 对应）：
  - 类比 Layer 2 (SQLite 会话历史)：前置结果作为"历史"注入
  - 类比 Layer 1 (工作记忆)：LLM 的 context window
  - 类比 Memory Flush Pass 1：依赖关系解析
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
import logging

from .skill_loader import SkillMetadata, SkillParameter

logger = logging.getLogger(__name__)


@dataclass
class SkillContext:
    """
    Skill 执行上下文（工作记忆）
    
    包含：
      1. 当前 skill 的元数据
      2. 用户输入参数
      3. 前置 skills 的执行结果（依赖注入）
      4. 全局配置
    """
    metadata: SkillMetadata
    user_params: Dict[str, Any]  # 用户提供的参数
    dependency_results: Dict[str, Any]  # 前置 skill 结果：{skill_name: result}
    config: Dict[str, Any]  # 全局配置
    
    def get_input_params(self) -> Dict[str, Any]:
        """获取最终的输入参数（用户参数 + 依赖结果注入）"""
        params = dict(self.user_params)
        
        # 从依赖结果中自动注入同名参数
        # 例：前置 skill "get-username" 的结果自动作为 "username" 参数
        for dep_name, result in self.dependency_results.items():
            # 规则：skill-name 的结果作为 skill_name 参数
            param_name = dep_name.replace("-", "_")
            if any(p.name == param_name for p in self.metadata.parameters):
                params[param_name] = result
        
        return params
    
    def validate_params(self) -> Tuple[bool, List[str]]:
        """验证参数完整性与类型正确性"""
        errors = []
        params = self.get_input_params()
        
        for skill_param in self.metadata.parameters:
            if skill_param.name not in params:
                if skill_param.required:
                    errors.append(
                        f"必需参数 '{skill_param.name}' 缺失"
                    )
                elif skill_param.default is not None:
                    params[skill_param.name] = skill_param.default
            else:
                # 类型检查
                value = params[skill_param.name]
                if not skill_param.validate(value):
                    errors.append(
                        f"参数 '{skill_param.name}' 类型错误："
                        f"期望 {skill_param.type}，得到 {type(value).__name__}"
                    )
        
        return len(errors) == 0, errors
    
    def to_prompt(self) -> str:
        """
        将上下文转换为 LLM prompt 前缀
        （如果 skill 使用 LLM，可注入此 prompt）
        """
        prompt_parts = []
        
        # 第1部分：Skill 描述
        prompt_parts.append(f"## Skill: {self.metadata.name}")
        prompt_parts.append(f"版本: {self.metadata.version}")
        prompt_parts.append(f"描述: {self.metadata.description}")
        prompt_parts.append("")
        
        # 第2部分：输入参数
        params = self.get_input_params()
        if params:
            prompt_parts.append("## 输入参数")
            for key, value in params.items():
                prompt_parts.append(f"- {key}: {value}")
            prompt_parts.append("")
        
        # 第3部分：依赖结果
        if self.dependency_results:
            prompt_parts.append("## 前置结果（依赖注入）")
            for dep_name, result in self.dependency_results.items():
                result_str = str(result)[:200]  # 截断太长的结果
                prompt_parts.append(f"- {dep_name}: {result_str}")
            prompt_parts.append("")
        
        return "\n".join(prompt_parts)


class ContextBuilder:
    """
    上下文构建器
    
    职责：
      1. 管理依赖关系（图）
      2. 收集前置结果
      3. 组装 SkillContext
      4. 参数验证
    
    类比 Memory Flush 的 Pass 1：
      - 解析对话中的依赖信息
      - 整理成结构化的 context
    """
    
    def __init__(self, registry):
        """
        Args:
            registry: SkillRegistry 实例
        """
        self.registry = registry
        self._execution_results: Dict[str, Any] = {}  # 缓存已执行的结果
    
    def build_context(
        self,
        skill_name: str,
        user_params: Dict[str, Any],
        dependency_results: Dict[str, Any] = None,
        config: Dict[str, Any] = None,
    ) -> Tuple[SkillContext, List[str]]:
        """
        为指定 skill 构建执行上下文
        
        Returns:
            (SkillContext, error_messages)
        """
        errors = []
        
        # 获取 skill 元数据
        metadata = self.registry.get(skill_name)
        if not metadata:
            errors.append(f"Skill not found: {skill_name}")
            return None, errors
        
        # 合并依赖结果
        if dependency_results is None:
            dependency_results = {}
        
        # 创建上下文
        context = SkillContext(
            metadata=metadata,
            user_params=user_params,
            dependency_results=dependency_results,
            config=config or {},
        )
        
        # 验证参数
        valid, param_errors = context.validate_params()
        if not valid:
            errors.extend(param_errors)
        
        return context, errors
    
    def build_chain_contexts(
        self,
        skill_names: List[str],
        user_params: Dict[str, Any],
        config: Dict[str, Any] = None,
    ) -> Tuple[Dict[str, SkillContext], List[str]]:
        """
        为一个 skill 链构建所有上下文
        
        Args:
            skill_names: skill 名称列表（可能有依赖关系）
            user_params: 用户参数（会传递给所有 skills）
            config: 全局配置
        
        Returns:
            ({skill_name: SkillContext}, error_messages)
        
        流程（对应 Memory Flush 三步）：
          Step 1: 拓扑排序，确定执行顺序
          Step 2: 逐个构建上下文，收集依赖关系
          Step 3: 验证完整性
        """
        errors = []
        contexts = {}
        
        # Step 1: 拓扑排序
        try:
            sorted_names = self.registry.topological_sort(skill_names)
        except Exception as e:
            errors.append(f"依赖分析失败: {e}")
            return contexts, errors
        
        # Step 2: 逐个构建
        for skill_name in sorted_names:
            # 收集前置依赖结果
            metadata = self.registry.get(skill_name)
            if not metadata:
                errors.append(f"Skill not found: {skill_name}")
                continue
            
            dependency_results = {}
            for dep_name in metadata.dependencies:
                if dep_name in self._execution_results:
                    dependency_results[dep_name] = self._execution_results[dep_name]
            
            # 构建上下文
            context, ctx_errors = self.build_context(
                skill_name,
                user_params,
                dependency_results,
                config,
            )
            
            if context:
                contexts[skill_name] = context
            errors.extend(ctx_errors)
        
        # Step 3: 验证
        if errors:
            logger.warning(f"上下文构建完成，但存在 {len(errors)} 个错误")
        
        return contexts, errors
    
    def inject_execution_result(self, skill_name: str, result: Any):
        """
        注入已执行的 skill 结果（供后续依赖使用）
        
        这对应 Memory Flush Pass 2：
          - 执行完成 → 结果持久化 → 注入到下一步
        """
        self._execution_results[skill_name] = result
        logger.debug(f"注入结果: {skill_name}")
    
    def get_execution_results(self) -> Dict[str, Any]:
        """获取所有已执行的结果"""
        return dict(self._execution_results)
    
    def clear_execution_results(self):
        """清空执行结果缓存"""
        self._execution_results.clear()


def resolve_dependencies(
    metadata: SkillMetadata,
    registry,
) -> List[str]:
    """
    递归解析依赖关系
    
    Returns:
        依赖链：[dep1, dep2, ..., target]
    """
    deps = []
    
    def visit(name: str, visited: set):
        if name in visited:
            return
        visited.add(name)
        
        meta = registry.get(name)
        if not meta:
            return
        
        for dep_name in meta.dependencies:
            visit(dep_name, visited)
        
        deps.append(name)
    
    visit(metadata.name, set())
    return deps
