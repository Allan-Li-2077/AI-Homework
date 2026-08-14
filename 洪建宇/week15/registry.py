"""SubAgent 注册表与健康检查管理。

维护当前所有可用 SubAgent 的元信息，支持静态注册（启动时批量加载）与
动态注册（运行时创建/销毁），并提供按能力标签查询、负载感知选型与
心跳健康检查机制。
"""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from ..core.exceptions import NoAgentAvailableError
from ..core.models import HealthState
from ..monitor import get_monitor
from .base import BaseSubAgent


class AgentRegistry:
    """SubAgent 注册表。"""

    def __init__(self, max_heartbeat_fail: int = 3) -> None:
        self._agents: Dict[str, BaseSubAgent] = {}
        self._max_heartbeat_fail = max_heartbeat_fail
        self._monitor = get_monitor()

    # ---- 注册 / 注销 ----
    def register(self, agent: BaseSubAgent) -> None:
        self._agents[agent.name] = agent
        self._monitor.emit(
            "_global", "agent_registered", "registry",
            {"agent": agent.name, "capabilities": agent.capabilities,
             "max_concurrency": agent.max_concurrency},
        )

    def unregister(self, name: str) -> bool:
        agent = self._agents.pop(name, None)
        if agent:
            self._monitor.emit("_global", "agent_unregistered", "registry", {"agent": name})
        return agent is not None

    def get(self, name: str) -> Optional[BaseSubAgent]:
        return self._agents.get(name)

    def all(self) -> List[BaseSubAgent]:
        return list(self._agents.values())

    def list_capabilities(self) -> List[str]:
        caps = set()
        for a in self._agents.values():
            caps.update(a.capabilities)
        return sorted(caps)

    # ---- 查询 / 选型 ----
    def query(self, capability: str, healthy_only: bool = True) -> List[BaseSubAgent]:
        """按能力标签查询可用 SubAgent。"""
        result = []
        for a in self._agents.values():
            if capability not in a.capabilities:
                continue
            if healthy_only and a.health_state != HealthState.HEALTHY:
                continue
            result.append(a)
        return result

    def select(
        self, capability: str, exclude: Optional[List[str]] = None
    ) -> Optional[BaseSubAgent]:
        """负载感知选型：在健康且有可用容量的 Agent 中选择负载最低者。"""
        exclude = exclude or []
        candidates = [
            a for a in self.query(capability)
            if a.name not in exclude and a.available_capacity > 0
        ]
        if not candidates:
            return None
        # 优先负载最低（current_load 最小），其次剩余容量最大
        candidates.sort(key=lambda a: (a.current_load, -a.available_capacity))
        return candidates[0]

    def available_capacity(self, capability: str) -> int:
        return sum(a.available_capacity for a in self.query(capability))

    def ensure_capability(self, capability: str) -> None:
        """确保某能力类型至少有一个健康 Agent，否则抛异常。"""
        if not self.query(capability):
            raise NoAgentAvailableError(capability)

    # ---- 健康检查 ----
    async def heartbeat_all(self) -> Dict[str, str]:
        """对所有 Agent 执行心跳探测，连续失败则标记不可用，恢复则标记健康。"""
        results: Dict[str, str] = {}
        for agent in list(self._agents.values()):
            try:
                ok = await asyncio.wait_for(agent.health_check(), timeout=5.0)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                agent._fail_streak = 0
                if agent.health_state != HealthState.HEALTHY:
                    agent.set_health(HealthState.HEALTHY)
                    self._monitor.emit(
                        "_global", "agent_recovered", "registry", {"agent": agent.name})
            else:
                agent._fail_streak += 1
                if agent._fail_streak >= self._max_heartbeat_fail:
                    agent.set_health(HealthState.UNAVAILABLE)
                    self._monitor.emit(
                        "_global", "agent_unavailable", "registry",
                        {"agent": agent.name, "fail_streak": agent._fail_streak},
                        level="WARNING")
            results[agent.name] = agent.health_state.value
        return results

    def mark_unavailable(self, name: str) -> None:
        agent = self._agents.get(name)
        if agent:
            agent.set_health(HealthState.UNAVAILABLE)

    def mark_available(self, name: str) -> None:
        agent = self._agents.get(name)
        if agent:
            agent._fail_streak = 0
            agent.set_health(HealthState.HEALTHY)

    def snapshot(self) -> List[Dict]:
        return [a.to_dict() for a in self._agents.values()]
