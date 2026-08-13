"""系统异常定义。"""


class SchedulerError(Exception):
    """调度系统基础异常。"""


class ValidationError(SchedulerError):
    """参数校验失败。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class DecomposeError(SchedulerError):
    """任务拆解失败。"""


class NoAgentAvailableError(SchedulerError):
    """无可用的 SubAgent。"""

    def __init__(self, capability: str):
        self.capability = capability
        super().__init__(f"能力类型 '{capability}' 下无可用 SubAgent")


class SubTaskTimeoutError(SchedulerError):
    """子任务执行超时。"""

    def __init__(self, subtask_id: str, timeout: float):
        self.subtask_id = subtask_id
        self.timeout = timeout
        super().__init__(f"子任务 {subtask_id} 执行超时（{timeout}s）")


class SubTaskCancelledError(SchedulerError):
    """子任务被取消。"""


class CyclicDependencyError(SchedulerError):
    """执行计划存在环依赖。"""
