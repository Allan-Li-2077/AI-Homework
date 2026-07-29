"""
Stage 3: Progressive Execution Engine (渐进式执行引擎)

职责：
  1. 按依赖顺序加载和执行 skills
  2. 流式输出中间结果
  3. 异常恢复与部分执行
  4. 执行事件的观察者模式

设计理念（与 week13 对应）：
  - 类比 Memory Flush 三步执行：Pass 1 → Pass 2 → Pass 3
  - 每个 skill 就是一个"Pass"，有独立的执行逻辑
  - 流式输出对应向量化、索引更新的"实时反馈"
"""

import asyncio
import traceback
from typing import Dict, List, Any, Optional, Callable, AsyncGenerator
from dataclasses import dataclass
from enum import Enum
import logging
from datetime import datetime

from .skill_loader import SkillLoader, SkillMetadata
from .skill_context import SkillContext, ContextBuilder

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    """执行状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ExecutionEvent:
    """执行事件（观察者模式的消息）"""
    timestamp: str
    stage: str  # "discovery", "context", "execution", "completion"
    skill_name: str
    status: ExecutionStatus
    message: str = ""
    result: Any = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（便于 JSON 序列化）"""
        return {
            "timestamp": self.timestamp,
            "stage": self.stage,
            "skill_name": self.skill_name,
            "status": self.status.value,
            "message": self.message,
            "result": result_to_serializable(self.result),
            "error": self.error,
        }


def result_to_serializable(obj: Any) -> Any:
    """将任意对象转换为可序列化的形式"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [result_to_serializable(x) for x in obj]
    elif isinstance(obj, dict):
        return {k: result_to_serializable(v) for k, v in obj.items()}
    else:
        return str(obj)


class SkillExecutor:
    """
    Skill 执行引擎
    
    核心设计：
      1. 加载阶段：发现所有 skills
      2. 规划阶段：解析依赖，确定执行顺序
      3. 执行阶段：渐进式执行，发送事件流
      4. 完成阶段：汇总结果，清理资源
    
    对应 Memory Flush 的三步：
      Pass 1: 发现 + 依赖分析（类比提取用户信息）
      Pass 2: 逐个执行（类比提取记忆条目）
      Pass 3: 结果汇总和持久化（类比向量化）
    """
    
    def __init__(
        self,
        skills_dir=None,
        on_event: Optional[Callable[[ExecutionEvent], None]] = None,
    ):
        self.skill_loader = SkillLoader(skills_dir)
        self.registry = None
        self.context_builder = None
        self.on_event = on_event  # 观察者回调
        self._skill_impls: Dict[str, Any] = {}  # 缓存加载的 skill 实现类
    
    async def initialize(self):
        """初始化执行器（发现所有 skills）"""
        # 发现阶段
        await self._emit_event(
            stage="discovery",
            skill_name="__system__",
            status=ExecutionStatus.PENDING,
            message="正在发现 skills...",
        )
        
        self.registry = self.skill_loader.discover_and_load()
        self.context_builder = ContextBuilder(self.registry)
        
        await self._emit_event(
            stage="discovery",
            skill_name="__system__",
            status=ExecutionStatus.SUCCESS,
            message=f"发现 {len(self.registry.list_skills())} 个 skills",
        )
    
    async def run_skill(
        self,
        skill_name: str,
        params: Dict[str, Any] = None,
        config: Dict[str, Any] = None,
    ) -> AsyncGenerator[ExecutionEvent, None]:
        """
        执行单个 skill，返回事件流
        
        使用方式（异步迭代）：
            async for event in executor.run_skill("demo-greeting", {"name": "Alice"}):
                print(event.message)
        """
        if not self.registry:
            await self.initialize()
        
        params = params or {}
        config = config or {}
        
        # 构建上下文
        await self._emit_event(
            stage="context",
            skill_name=skill_name,
            status=ExecutionStatus.PENDING,
            message="正在构建执行上下文...",
        )
        
        context, errors = self.context_builder.build_context(
            skill_name, params, config=config
        )
        
        if not context:
            await self._emit_event(
                stage="context",
                skill_name=skill_name,
                status=ExecutionStatus.FAILED,
                message="上下文构建失败",
                error="\n".join(errors),
            )
            return
        
        for error in errors:
            await self._emit_event(
                stage="context",
                skill_name=skill_name,
                status=ExecutionStatus.RUNNING,
                message=f"警告: {error}",
            )
        
        await self._emit_event(
            stage="context",
            skill_name=skill_name,
            status=ExecutionStatus.SUCCESS,
            message="执行上下文已就绪",
        )
        
        # 执行 skill
        async for event in self._execute_skill_impl(skill_name, context):
            yield event
    
    async def run_skill_chain(
        self,
        skill_names: List[str],
        params: Dict[str, Any] = None,
        config: Dict[str, Any] = None,
    ) -> AsyncGenerator[ExecutionEvent, None]:
        """
        链式执行多个 skills，返回事件流
        
        对应 Memory Flush 三步的完整流程：
          Step 1: 依赖分析
          Step 2: 逐个执行（注入前置结果）
          Step 3: 结果持久化
        """
        if not self.registry:
            await self.initialize()
        
        params = params or {}
        config = config or {}
        
        # Step 1: 依赖分析
        await self._emit_event(
            stage="discovery",
            skill_name="__chain__",
            status=ExecutionStatus.PENDING,
            message=f"正在分析链依赖: {', '.join(skill_names)}",
        )
        
        try:
            sorted_names = self.registry.topological_sort(skill_names)
            await self._emit_event(
                stage="discovery",
                skill_name="__chain__",
                status=ExecutionStatus.SUCCESS,
                message=f"执行顺序: {' → '.join(sorted_names)}",
            )
        except Exception as e:
            await self._emit_event(
                stage="discovery",
                skill_name="__chain__",
                status=ExecutionStatus.FAILED,
                message="依赖分析失败",
                error=str(e),
            )
            return
        
        # 构建所有上下文
        await self._emit_event(
            stage="context",
            skill_name="__chain__",
            status=ExecutionStatus.PENDING,
            message="正在构建所有上下文...",
        )
        
        contexts, errors = self.context_builder.build_chain_contexts(
            sorted_names, params, config
        )
        
        if errors:
            await self._emit_event(
                stage="context",
                skill_name="__chain__",
                status=ExecutionStatus.RUNNING,
                message=f"上下文构建完成，但有 {len(errors)} 个错误",
            )
        
        # Step 2: 逐个执行
        all_results = {}
        
        for skill_name in sorted_names:
            if skill_name not in contexts:
                await self._emit_event(
                    stage="execution",
                    skill_name=skill_name,
                    status=ExecutionStatus.SKIPPED,
                    message="跳过（上下文缺失）",
                )
                continue
            
            context = contexts[skill_name]
            
            # 执行并收集结果
            async for event in self._execute_skill_impl(skill_name, context):
                yield event
                
                if event.status == ExecutionStatus.SUCCESS:
                    all_results[skill_name] = event.result
                    # 注入结果供后续依赖使用
                    self.context_builder.inject_execution_result(skill_name, event.result)
        
        # Step 3: 汇总
        await self._emit_event(
            stage="completion",
            skill_name="__chain__",
            status=ExecutionStatus.SUCCESS,
            message=f"链执行完成，共 {len(all_results)} 个成功",
            result=all_results,
        )
    
    async def _execute_skill_impl(
        self,
        skill_name: str,
        context: SkillContext,
    ) -> AsyncGenerator[ExecutionEvent, None]:
        """
        执行 skill 的实现，返回事件流
        
        这是 Memory Flush Pass 2 的核心：
          - 加载实现
          - 调用执行
          - 发送中间事件
          - 处理异常
        """
        try:
            # 加载 skill 实现
            await self._emit_event(
                stage="execution",
                skill_name=skill_name,
                status=ExecutionStatus.PENDING,
                message="正在加载 skill 实现...",
            )
            
            skill_impl_class = self._load_skill_impl(context.metadata)
            
            await self._emit_event(
                stage="execution",
                skill_name=skill_name,
                status=ExecutionStatus.RUNNING,
                message="开始执行...",
            )
            
            # 创建实例并执行
            skill_impl = skill_impl_class(context)
            
            # 调用 execute（支持同步和异步）
            params = context.get_input_params()
            
            if asyncio.iscoroutinefunction(skill_impl.execute):
                result = await skill_impl.execute(**params)
            else:
                # 异步封装同步调用
                result = await asyncio.to_thread(skill_impl.execute, **params)
            
            # 成功
            await self._emit_event(
                stage="execution",
                skill_name=skill_name,
                status=ExecutionStatus.SUCCESS,
                message="执行成功",
                result=result,
            )
        
        except Exception as e:
            error_msg = traceback.format_exc()
            logger.error(f"Skill {skill_name} 执行失败: {error_msg}")
            
            await self._emit_event(
                stage="execution",
                skill_name=skill_name,
                status=ExecutionStatus.FAILED,
                message="执行失败",
                error=str(e),
            )
    
    def _load_skill_impl(self, metadata: SkillMetadata) -> Any:
        """加载 skill 的 Python 实现（支持缓存）"""
        if metadata.name in self._skill_impls:
            return self._skill_impls[metadata.name]
        
        skill_impl_class = self.skill_loader.load_skill_impl(metadata)
        self._skill_impls[metadata.name] = skill_impl_class
        
        return skill_impl_class
    
    async def _emit_event(
        self,
        stage: str,
        skill_name: str,
        status: ExecutionStatus,
        message: str = "",
        result: Any = None,
        error: Optional[str] = None,
    ):
        """发送执行事件"""
        event = ExecutionEvent(
            timestamp=datetime.now().isoformat(),
            stage=stage,
            skill_name=skill_name,
            status=status,
            message=message,
            result=result,
            error=error,
        )
        
        # 记录日志
        if status == ExecutionStatus.FAILED:
            logger.error(f"[{skill_name}] {message}: {error}")
        elif status == ExecutionStatus.SUCCESS:
            logger.info(f"[{skill_name}] {message}")
        else:
            logger.debug(f"[{skill_name}] {message}")
        
        # 回调观察者
        if self.on_event:
            self.on_event(event)
