"""Select a local Skill while keeping full instructions out of the base context."""

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from src.llm_config import get_chat_client
from src.skill_registry import SkillRegistry


@dataclass
class SkillRoute:
    selected: bool
    skill_name: str | None = None
    confidence: float = 0.0
    arguments: dict = field(default_factory=dict)
    reason: str = ""
    explicit: bool = False


class SkillRouter:
    def __init__(
        self,
        registry: SkillRegistry,
        confidence_threshold: float = 0.75,
        client_factory: Callable = get_chat_client,
    ):
        self.registry = registry
        self.confidence_threshold = confidence_threshold
        self.client_factory = client_factory

    def route(self, message: str) -> SkillRoute:
        explicit = self.parse_explicit(message)
        if explicit is not None:
            return explicit
        return self._route_with_llm(message)

    def parse_explicit(self, message: str) -> SkillRoute | None:
        match = re.match(r"^/skill\s+(\S+)(?:\s+([\s\S]+))?$", message.strip())
        if not match:
            return None
        name = match.group(1)
        request = (match.group(2) or "").strip()
        if self.registry.get(name) is None:
            available = ", ".join(s.name for s in self.registry.list())
            raise ValueError(f"未知 Skill '{name}'，可用 Skill: {available}")
        arguments = {"request": request}
        if name == "flash-card" and request:
            arguments["word"] = request.lower()
        if name == "baoyu-diagram" and request:
            arguments["topic"] = request
        return SkillRoute(
            selected=True,
            skill_name=name,
            confidence=1.0,
            arguments=arguments,
            reason="用户显式指定 Skill",
            explicit=True,
        )

    def _route_with_llm(self, message: str) -> SkillRoute:
        prompt = f"""你是 Skill 路由器。根据用户请求判断是否需要调用一个 Skill。

可用 Skill：
{self.registry.catalog_for_prompt()}

只有用户明确要求生成对应产物时才选择 Skill。解释概念、询问含义、普通聊天不要选择。
只返回 JSON：
{{"selected": true/false, "skill_name": "名称或null", "confidence": 0到1, "arguments": {{}}, "reason": "简短原因"}}

flash-card 的 arguments 使用 word；baoyu-diagram 使用 topic、diagram_type。
用户请求：{message}"""
        try:
            client, model = self.client_factory()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            data = self._parse_json(response.choices[0].message.content or "")
            name = data.get("skill_name")
            confidence = float(data.get("confidence", 0.0))
            selected = bool(data.get("selected"))
            if not selected or confidence < self.confidence_threshold:
                return SkillRoute(selected=False, confidence=confidence, reason=str(data.get("reason", "")))
            if not isinstance(name, str) or self.registry.get(name) is None:
                return SkillRoute(selected=False, reason="路由结果包含未知 Skill")
            arguments = data.get("arguments")
            return SkillRoute(
                selected=True,
                skill_name=name,
                confidence=confidence,
                arguments=arguments if isinstance(arguments, dict) else {},
                reason=str(data.get("reason", "")),
            )
        except Exception as exc:
            return SkillRoute(selected=False, reason=f"Skill 路由失败，已回退普通对话: {exc}")

    @staticmethod
    def _parse_json(text: str) -> dict:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise ValueError("Skill 路由未返回 JSON")
        data = json.loads(match.group())
        if not isinstance(data, dict):
            raise ValueError("Skill 路由结果必须是对象")
        return data
