from dataclasses import dataclass
from typing import AsyncGenerator, Any, Callable
from src.session_db import SessionDB
@dataclass
class HarnessContext:
    session_id: int
    step_index: int
    state: dict
    interrupt_flag: bool = False
class BaseProgressiveHarness:
    def __init__(self, db: SessionDB):
        self.db = db
        self.ctx: HarnessContext | None = None
    def init_context(self, session_id: int):
        self.ctx = HarnessContext(session_id=session_id, step_index=0, state={})
    async def run_progressive(self, runner: Callable) -> AsyncGenerator[Any, None]:
        """通用分步执行包装，支持中断、断点保存"""
        if not self.ctx:
            raise RuntimeError("Harness context not initialized")
        async for chunk in runner():
            if self.ctx.interrupt_flag:
                self.db.save_checkpoint(self.ctx.session_id, "interrupt", "interrupted", self.ctx.state)
                break
            yield chunk
            self.ctx.step_index += 1