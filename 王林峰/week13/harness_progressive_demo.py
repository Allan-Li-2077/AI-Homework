"""
Harness 渐进式执行完整演示脚本
运行：python examples/harness_progressive_demo.py
功能：
1. 初始化数据库、记忆加载器、Flush执行器
2. 渐进分层加载记忆（分页懒加载）
3. 分步断点执行Memory Flush，支持中断续跑
4. 快照保存/回滚
5. 读取执行追踪日志
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.session_db import SessionDB
from src.memory_loader import MemoryLoader
from src.vector_store import VectorStore
from src.fts_store import FTSStore
from src.retrieval import HybridRetriever
from src.memory_flush import MemoryFlusher
from src.harness import FlushHarness, MemoryLoadHarness, TraceLogger
from src.reset import cmd_backup

async def main():
    # 初始化底层单例
    db = SessionDB()
    loader = MemoryLoader()
    vs = VectorStore()
    fts = FTSStore()
    retriever = HybridRetriever(vs, fts)
    flusher = MemoryFlusher()

    # 初始化Harness组件
    trace_logger = TraceLogger(log_path=Path(__file__).parent.parent / "outputs/harness_trace.log")
    flush_harness = FlushHarness(db=db, flusher=flusher)
    mem_harness = MemoryLoadHarness(db=db, loader=loader, trace_logger=trace_logger)

    # 创建新会话
    session_id = db.new_session()
    print(f"=== 创建新会话 ID: {session_id} ===")

    # 模拟对话消息
    test_messages = [
        {"role": "user", "content": "我日常喜欢喝冰美式，不喝加糖奶茶"},
        {"role": "assistant", "content": "了解，我会记住你的饮品偏好。"},
        {"role": "user", "content": "每周日凌晨3点自动整理压缩我的记忆"},
    ]

    # 1. 渐进式分层加载记忆
    print("\n=== 1. 渐进分页加载所有记忆分层 ===")
    mem_harness.init_context(session_id=session_id)
    async for chunk in mem_harness.step_runner(chunk_size=3):
        print(f"分层: {chunk.layer_name} | 分片完成: {chunk.finished}")
        print(f"分片预览: {chunk.partial_content[:120]}...\n")

    # 2. 分步执行 Flush（断点续跑）
    print("=== 2. 分步执行 Memory Flush 流程 ===")
    flush_harness.init_context(session_id=session_id)
    async for step in flush_harness.step_runner(test_messages):
        print(f"执行步骤: {step['step']} | 数据: {step['data']}")
        trace_logger.write_trace(session_id, step)
        # 模拟中途中断：取消注释测试断点保存
        # flush_harness.ctx.interrupt_flag = True
        # break

    # 3. 创建记忆快照
    print("\n=== 3. 创建当前记忆快照 ===")
    snap_name = cmd_backup(name="harness_demo_snap")
    print(f"快照已保存: backups/{snap_name}")

    # 4. 读取全部执行追踪日志
    print("\n=== 4. 读取本次会话执行追踪日志 ===")
    trace_logs = trace_logger.read_trace(session_id=session_id, limit=50)
    for log in trace_logs[-5:]:
        print(f"[{log['ts']}] {log['payload']}")

    print("\n=== Harness 渐进执行演示全部完成 ===")

if __name__ == "__main__":
    asyncio.run(main())