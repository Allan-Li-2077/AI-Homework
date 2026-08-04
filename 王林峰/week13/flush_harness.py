from src.harness.base_harness import BaseProgressiveHarness
from src.memory_flush import MemoryFlusher
class FlushHarness(BaseProgressiveHarness):
    def __init__(self, db, flusher: MemoryFlusher):
        super().__init__(db)
        self.flusher = flusher
    async def step_runner(self, messages):
        async for step_result in self.flusher.flush_progressive(messages, self.ctx.session_id, self.db):
            self.ctx.state[step_result["step"]] = step_result
            yield step_result