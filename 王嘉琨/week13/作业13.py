from __future__ import annotations
import abc
import uuid
import typing
import dataclasses
from enum import Enum
from typing import Any, Optional, Dict, List, Callable, Generator

# ===================== 基础枚举 & 数据结构 =====================
class SkillState(Enum):
    PENDING = "pending"      # 等待加载
    LOADED = "loaded"       # 已加载未执行
    RUNNING = "running"     # 执行中
    COMPLETED = "completed" # 执行成功
    FAILED = "failed"       # 执行失败
    UNLOADED = "unloaded"   # 已卸载


@dataclasses.dataclass
class SkillContext:
    """全局执行上下文，所有Skill共享"""
    session_id: str
    user_query: Optional[str] = None
    chat_history: List[Dict[str, str]] = dataclasses.field(default_factory=list)
    shared_data: Dict[str, Any] = dataclasses.field(default_factory=dict)
    snapshot: Optional[Dict[str, Any]] = None  # 断点快照

    def save_snapshot(self):
        """生成上下文快照用于断点恢复"""
        self.snapshot = dataclasses.asdict(self)

    @classmethod
    def restore_from_snapshot(cls, snap: Dict[str, Any]) -> "SkillContext":
        return cls(**snap)


@dataclasses.dataclass
class SkillResult:
    """单次Skill执行返回结果"""
    success: bool
    output: Any
    error: Optional[Exception] = None
    stop_chain: bool = False  # 是否终止后续skill链路


# ===================== Skill 抽象基类 =====================
class BaseSkill(abc.ABC):
    skill_name: str
    lazy_load: bool = True  # 是否开启渐进懒加载

    def __init__(self):
        self.state: SkillState = SkillState.PENDING

    def load(self) -> None:
        """渐进加载：初始化权重/资源/连接，懒加载模式首次执行才调用"""
        if self.state not in (SkillState.PENDING, SkillState.UNLOADED):
            return
        self._load_resource()
        self.state = SkillState.LOADED

    def unload(self) -> None:
        """释放资源，节约内存"""
        self._release_resource()
        self.state = SkillState.UNLOADED

    @abc.abstractmethod
    def _load_resource(self) -> None:
        """子类实现：加载资源（模型、客户端、配置等）"""
        ...

    @abc.abstractmethod
    def _release_resource(self) -> None:
        """子类实现：销毁资源"""
        ...

    @abc.abstractmethod
    def execute(self, ctx: SkillContext) -> SkillResult:
        """业务执行逻辑"""
        ...

    def run(self, ctx: SkillContext) -> SkillResult:
        """统一入口：自动懒加载 + 执行状态流转"""
        if self.lazy_load and self.state == SkillState.PENDING:
            self.load()
        self.state = SkillState.RUNNING
        try:
            result = self.execute(ctx)
            self.state = SkillState.COMPLETED if result.success else SkillState.FAILED
            return result
        except Exception as e:
            self.state = SkillState.FAILED
            return SkillResult(success=False, output=None, error=e, stop_chain=True)


# ===================== 核心 Harness 执行调度器 =====================
class SkillHarness:
    def __init__(self):
        # 注册池：skill_name -> skill实例
        self.skill_registry: Dict[str, BaseSkill] = {}
        # 执行链路队列（有序执行）
        self.execution_chain: List[str] = []
        # 回调钩子
        self.on_skill_start: Optional[Callable[[str, SkillContext], None]] = None
        self.on_skill_end: Optional[Callable[[str, SkillContext, SkillResult], None]] = None

    def register_skill(self, skill: BaseSkill):
        """注册Skill，支持后续动态添加"""
        self.skill_registry[skill.skill_name] = skill

    def set_execution_chain(self, skill_names: List[str]):
        """设置顺序执行链路"""
        self.execution_chain = skill_names

    def get_skill(self, name: str) -> BaseSkill:
        if name not in self.skill_registry:
            raise KeyError(f"Skill [{name}] 未注册")
        return self.skill_registry[name]

    def run_chain(
        self,
        ctx: Optional[SkillContext] = None,
        resume_snapshot: Optional[Dict[str, Any]] = None
    ) -> SkillContext:
        """
        完整串行执行链路
        :param ctx: 会话上下文
        :param resume_snapshot: 传入快照实现断点续跑
        :return: 最终上下文
        """
        if resume_snapshot is not None:
            ctx = SkillContext.restore_from_snapshot(resume_snapshot)
        elif ctx is None:
            ctx = SkillContext(session_id=str(uuid.uuid4()))

        for skill_name in self.execution_chain:
            skill = self.get_skill(skill_name)

            if self.on_skill_start:
                self.on_skill_start(skill_name, ctx)

            res = skill.run(ctx)

            if self.on_skill_end:
                self.on_skill_end(skill_name, ctx, res)

            # 中断链路
            if res.stop_chain:
                break

            # 可选：执行完成后自动卸载释放内存（渐进内存优化策略）
            # skill.unload()

        return ctx

    def stream_run_chain(self, ctx: SkillContext) -> Generator[tuple[str, SkillResult], None, SkillContext]:
        """
        流式迭代执行，逐步产出每个skill结果（适合Agent流式输出）
        yield (skill_name, result)
        """
        for skill_name in self.execution_chain:
            skill = self.get_skill(skill_name)
            result = skill.run(ctx)
            yield skill_name, result
            if result.stop_chain:
                break
        return ctx

    def unload_all(self):
        """批量卸载所有skill，释放全部资源"""
        for skill in self.skill_registry.values():
            skill.unload()


# ===================== 示例：自定义Skill实现 =====================
# Demo1：多轮对话记忆管理Skill
class ChatMemorySkill(BaseSkill):
    skill_name = "chat_memory"

    def _load_resource(self) -> None:
        print("[LOAD] 加载对话记忆模块")

    def _release_resource(self) -> None:
        print("[UNLOAD] 释放对话记忆模块")

    def execute(self, ctx: SkillContext) -> SkillResult:
        # 将用户最新消息写入对话历史
        if ctx.user_query:
            ctx.chat_history.append({"role": "user", "content": ctx.user_query})
        return SkillResult(success=True, output={"history_len": len(ctx.chat_history)})


# Demo2：工具调用循环Skill（对应你之前天气循环调用需求）
class ToolCallSkill(BaseSkill):
    skill_name = "tool_caller"

    def _load_resource(self) -> None:
        print("[LOAD] 加载工具调用客户端")

    def _release_resource(self) -> None:
        print("[UNLOAD] 释放工具调用客户端")

    def execute(self, ctx: SkillContext) -> SkillResult:
        # 模拟循环调用工具逻辑
        query = ctx.user_query
        mock_resp = f"工具调用结果：{query} 的数据已获取"
        ctx.shared_data["tool_result"] = mock_resp
        return SkillResult(success=True, output=mock_resp)


# Demo3：LLM生成回复Skill
class LLMGenerateSkill(BaseSkill):
    skill_name = "llm_generate"

    def _load_resource(self) -> None:
        print("[LOAD] 加载LLM推理实例【渐进懒加载，首次运行才触发】")

    def _release_resource(self) -> None:
        print("[UNLOAD] 释放LLM模型显存/内存")

    def execute(self, ctx: SkillContext) -> SkillResult:
        reply = f"模型回复：{ctx.shared_data.get('tool_result','无工具信息')}"
        ctx.chat_history.append({"role": "assistant", "content": reply})
        return SkillResult(success=True, output=reply)


# ===================== 运行 Demo =====================
if __name__ == "__main__":
    # 1. 实例化调度Harness
    harness = SkillHarness()

    # 2. 注册所有Skill
    harness.register_skill(ChatMemorySkill())
    harness.register_skill(ToolCallSkill())
    harness.register_skill(LLMGenerateSkill())

    # 3. 设置执行链路：对话记忆 → 工具循环调用 → LLM生成
    harness.set_execution_chain(["chat_memory", "tool_caller", "llm_generate"])

    # 4. 初始化上下文（适配Agent多轮对话）
    context = SkillContext(session_id="agent_001", user_query="查询杭州今日天气")

    # 5. 执行整条链路
    final_ctx = harness.run_chain(context)

    print("\n===== 执行结果 =====")
    print("对话历史：", final_ctx.chat_history)

    # 演示：流式逐步执行（适合流式Agent输出）
    print("\n===== 流式迭代执行演示 =====")
    stream_ctx = SkillContext(session_id="agent_002", user_query="查询北京今日天气")
    for name, res in harness.stream_run_chain(stream_ctx):
        print(f"【{name}】输出: {res.output}")

    # 全部卸载，释放资源
    harness.unload_all()
