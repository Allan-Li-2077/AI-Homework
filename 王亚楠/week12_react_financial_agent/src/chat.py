"""
ChatSession — 多轮对话管理

封装 ReAct Agent 的对话状态，支持连续追问，保持完整上下文。

使用方式：
  from chat import ChatSession
  session = ChatSession(mode="manual", memory=store, session_id="default")

  for step in session.send("茅台2023年毛利率是多少？"):
      if step["type"] == "action":
          print(f"  [{step['action']}] {step['observation'][:80]}")
      elif step["type"] == "final":
          print(f"  => {step['answer']}")

  # 追问：Agent 知道上下文
  for step in session.send("对比一下五粮液"):
      ...

  session.clear()  # 重置对话（保留持久化记忆）
"""

import logging
from typing import Generator, Optional

logger = logging.getLogger(__name__)


class ChatSession:
    """管理 Agent 的多轮对话状态

    messages 列表在多次 send() 调用间持续累积，
    使 Agent 能理解上下文中的指代和追问。
    """

    def __init__(
        self,
        mode: str = "manual",
        memory=None,
        session_id: str = "default",
    ):
        """
        Args:
            mode: "manual" 或 "fc"
            memory: MemoryStore 实例（可选）
            session_id: 会话标识
        """
        if mode not in ("manual", "fc"):
            raise ValueError(f"mode 必须是 'manual' 或 'fc'，收到: {mode}")
        self.mode = mode
        self.memory = memory
        self.session_id = session_id
        self.messages = None  # 首轮 send() 时初始化
        self.turns: list[dict] = []  # 每轮 Q&A 摘要

    # ── 核心方法 ──────────────────────────────────────────────────────────

    def send(
        self, question: str, max_steps: int = 10
    ) -> Generator[dict, None, None]:
        """发送一条消息并流式获取 ReAct 步骤

        首轮：自动构建 System Prompt（含记忆上下文）
        后续轮：追加用户消息到已有对话历史

        Yields:
            dict: ReAct 步骤（与 run() 格式一致）
            最后一个 step 附带 "_messages" 键，值为完整对话历史
        """
        if self.mode == "manual":
            from react_manual import run
        else:
            from react_function_calling import run

        for step in run(
            question,
            max_steps=max_steps,
            memory=self.memory,
            session_id=self.session_id,
            messages=self.messages,
        ):
            # 提取更新后的 messages（由 run() 注入）
            if "_messages" in step:
                self.messages = step.pop("_messages")
            yield step

        # 记录本轮摘要
        self._record_turn(question)

    def _record_turn(self, question: str):
        """内部：记录一轮对话摘要"""
        self.turns.append({
            "question": question,
            "turn": len(self.turns) + 1,
        })

    # ── 对话管理 ──────────────────────────────────────────────────────────

    def clear(self):
        """重置当前对话上下文（持久化记忆不受影响）"""
        self.messages = None
        self.turns = []
        logger.info(f"对话已重置 (session={self.session_id})")

    def get_history(self) -> list[dict]:
        """获取用户可见的对话历史（Q&A 摘要）"""
        result = []
        for t in self.turns:
            entry = {"turn": t["turn"], "question": t["question"]}
            # 尝试从 messages 中提取回答
            for msg in (self.messages or []):
                if msg["role"] == "assistant" and msg.get("content"):
                    entry["answer"] = msg["content"][:300]
            result.append(entry)
        return result

    def get_summary(self) -> str:
        """生成对话摘要文本"""
        if not self.turns:
            return "（空对话）"
        lines = [f"会话 {self.session_id}，共 {len(self.turns)} 轮："]
        for t in self.turns:
            lines.append(f"  [{t['turn']}] {t['question']}")
        return "\n".join(lines)

    def is_active(self) -> bool:
        """是否有进行中的对话"""
        return self.messages is not None and len(self.messages) > 1

    def turn_count(self) -> int:
        return len(self.turns)
