"""
技能注册表 — 内存注册中心 + OpenAI tool schema 管理

职责：
- 维护技能名称 → Skill 对象的映射
- 提供工具调用分发（按名称查找并执行技能）
- 统计技能使用情况
- 生成 OpenAI function calling 兼容的 tools 参数
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .skill_loader import Skill, SkillLoader
from .config import HarnessConfig

logger = logging.getLogger("harness.registry")


@dataclass
class ToolCall:
    """一次工具调用的记录"""
    skill_name: str
    instruction: str = ""
    success: bool = True
    error: Optional[str] = None


class SkillRegistry:
    """
    技能注册表

    提供：
    - 遍历所有已注册技能
    - 生成 OpenAI tool schemas
    - 分发工具调用
    - 内置工具注册（calculator 等）
    """

    def __init__(self, loader: SkillLoader, config: HarnessConfig):
        self.loader = loader
        self.config = config
        self._custom_tools: dict[str, Callable] = {}        # name → callable
        self._custom_schemas: dict[str, dict] = {}          # name → tool schema
        self._call_history: list[ToolCall] = []
        self._executor: Optional[Callable] = None            # 外部注入的执行器

    # ── 自定义工具 ────────────────────────────────────────

    def register_tool(self, name: str, func: Callable, schema: Optional[dict] = None):
        """注册一个自定义工具（如 calculator）"""
        self._custom_tools[name] = func
        if schema:
            self._custom_schemas[name] = schema
        logger.debug("注册自定义工具: %s", name)

    def unregister_tool(self, name: str):
        """移除自定义工具"""
        self._custom_tools.pop(name, None)
        self._custom_schemas.pop(name, None)

    def set_executor(self, executor: Callable):
        """
        设置技能执行器。executor(skill: Skill, instruction: str) -> str
        """
        self._executor = executor

    # ── Schema 生成 ───────────────────────────────────────

    def get_tool_schemas(self) -> list[dict]:
        """
        生成完整的 OpenAI tools 参数列表。

        包含：所有已索引的技能 + 注册的自定义工具
        """
        schemas = self.loader.list_tool_schemas()

        # 合并自定义工具 schemas
        for name, schema in self._custom_schemas.items():
            schemas.append(schema)

        return schemas

    def get_tool_schemas_by_names(self, names: list[str]) -> list[dict]:
        """按名称子集生成 schemas"""
        schemas = self.loader.list_tool_schemas(names=names)
        for name in names:
            if name in self._custom_schemas:
                schemas.append(self._custom_schemas[name])
        return schemas

    # ── 工具调用执行 ──────────────────────────────────────

    def execute(self, tool_name: str, **kwargs) -> str:
        """
        执行工具调用。

        优先查找自定义工具，其次查找技能。

        Args:
            tool_name: 工具/技能名称
            **kwargs: 工具参数

        Returns:
            工具执行结果字符串
        """
        call = ToolCall(skill_name=tool_name)

        # 1. 尝试自定义工具
        if tool_name in self._custom_tools:
            try:
                result = self._custom_tools[tool_name](**kwargs)
                call.instruction = str(kwargs)
                self._call_history.append(call)
                return str(result)
            except Exception as e:
                call.success = False
                call.error = str(e)
                self._call_history.append(call)
                return f"工具执行出错 [{tool_name}]: {e}"

        # 2. 尝试技能
        skill = self.loader.get(tool_name)
        if skill is None:
            call.success = False
            call.error = f"未知工具: {tool_name}"
            self._call_history.append(call)
            return f"未知工具 '{tool_name}'，可用工具: {self.list_names()}"

        # 3. 懒加载技能 spec
        skill = self.loader.load(tool_name)
        if skill is None:
            call.success = False
            call.error = f"技能加载失败: {tool_name}"
            self._call_history.append(call)
            return f"技能 '{tool_name}' 加载失败"

        # 4. 通过执行器执行
        instruction = kwargs.get("instruction", str(kwargs))
        call.instruction = instruction

        if self._executor is not None:
            try:
                result = self._executor(skill, instruction)
                self._call_history.append(call)
                return result
            except Exception as e:
                call.success = False
                call.error = str(e)
                self._call_history.append(call)
                return f"技能执行出错 [{tool_name}]: {e}"

        # 无执行器：返回技能 spec 作为参考
        self._call_history.append(call)
        return (
            f"技能 [{skill.name}] 已加载，但无执行器。"
            f"技能规格 ({len(skill.spec)} 字符) 可供参考。"
            f"可用脚本: {skill.scripts}"
        )

    # ── 查询 ──────────────────────────────────────────────

    def list_names(self) -> list[str]:
        """所有可调用工具名称（技能 + 自定义工具）"""
        names = self.loader.list_names()
        names.extend(self._custom_tools.keys())
        return sorted(names)

    def get_call_history(self, limit: int = 20) -> list[ToolCall]:
        return self._call_history[-limit:]

    def clear_history(self):
        self._call_history.clear()

    @property
    def total_calls(self) -> int:
        return len(self._call_history)
