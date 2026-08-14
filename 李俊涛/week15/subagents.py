

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Task, TaskResult
from .backends import Backend, CallableBackend, LLMBackend, ShellBackend


@dataclass
class SubAgentSpec:
    """子智能体的构造规格（工厂据此动态创建）。"""
    name: str
    role: str = "worker"
    backend_type: str = "callable"      # callable | llm | shell
    backend_config: dict = field(default_factory=dict)


class SubAgent:
    """一个隔离的任务执行单元。"""

    def __init__(self, name: str, role: str, backend: Backend):
        self.name = name
        self.role = role
        self.backend = backend
        self.last_usage: dict | None = None   # 最近一次执行的 token 用量

    def run(self, task: Task) -> Any:
        """执行任务，返回后端结果（异常向上抛出，由编排层捕获隔离）。"""
        value = self.backend.run(task)
        # 把后端产生的 token 用量透传出来（Callable/Shell 后端为 None）
        self.last_usage = getattr(self.backend, "last_usage", None)
        return value

    def __repr__(self) -> str:
        return f"SubAgent(name={self.name!r}, role={self.role!r}, backend={type(self.backend).__name__})"


class SubAgentFactory:
    """根据规格动态创建 SubAgent。"""

    @staticmethod
    def create(spec: SubAgentSpec) -> SubAgent:
        bt = spec.backend_type
        if bt == "callable":
            backend: Backend = CallableBackend(**spec.backend_config)
        elif bt == "llm":
            backend = LLMBackend(**spec.backend_config)
        elif bt == "shell":
            backend = ShellBackend(**spec.backend_config)
        else:
            raise ValueError(f"未知后端类型: {bt!r}（可选 callable/llm/shell）")
        return SubAgent(spec.name, spec.role, backend)
