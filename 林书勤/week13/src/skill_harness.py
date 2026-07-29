"""
Skill Harness - 主程序与 API 接口

提供：
  1. 同步 API（包装异步执行器）
  2. CLI 接口（命令行工具）
  3. 事件流管理（SSE 风格）
  4. 完整的生命周期管理
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
import logging

from .skill_loader import SkillLoader
from .skill_context import ContextBuilder
from .skill_executor import SkillExecutor, ExecutionEvent, ExecutionStatus
from .skill_state import SkillState, ExecutionRecord

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class SkillHarness:
    """
    主 Harness 类
    
    提供高级 API，对外隐藏异步细节
    """
    
    def __init__(
        self,
        skills_dir: Path = None,
        state_dir: Path = None,
        auto_save: bool = True,
    ):
        self.skills_dir = skills_dir or Path(__file__).parent.parent / "skills"
        self.state_dir = state_dir or Path(__file__).parent.parent / "state"
        self.auto_save = auto_save
        
        # 初始化各组件
        self.executor = SkillExecutor(
            skills_dir=self.skills_dir,
            on_event=self._on_execution_event,
        )
        self.state = SkillState(self.state_dir)
        
        # 事件流缓冲
        self._events: List[ExecutionEvent] = []
        self._current_execution_events: List[ExecutionEvent] = []
    
    def initialize(self):
        """同步初始化"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.executor.initialize())
        finally:
            loop.close()
    
    def discover_skills(self) -> List[Dict[str, Any]]:
        """发现并返回所有 skills 的信息"""
        if not self.executor.registry:
            self.initialize()
        
        skills_info = []
        for metadata in self.executor.registry.list_skills():
            skills_info.append({
                "name": metadata.name,
                "version": metadata.version,
                "description": metadata.description,
                "trigger": metadata.trigger,
                "dependencies": metadata.dependencies,
                "parameters": [
                    {
                        "name": p.name,
                        "type": p.type,
                        "required": p.required,
                        "default": p.default,
                        "description": p.description,
                    }
                    for p in metadata.parameters
                ],
            })
        
        return skills_info
    
    def run_skill(
        self,
        skill_name: str,
        params: Dict[str, Any] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        执行单个 skill（同步）
        
        Args:
            skill_name: skill 名称
            params: 输入参数
            use_cache: 是否使用缓存结果
        
        Returns:
            {
                "status": "success" | "failed",
                "result": ...,
                "events": [ExecutionEvent...],
                "duration_ms": ...
            }
        """
        start_time = datetime.now()
        self._current_execution_events.clear()
        
        # 检查缓存
        if use_cache:
            cached = self.state.get_cached_result(skill_name)
            if cached:
                logger.info(f"使用缓存: {skill_name}")
                return {
                    "status": "success",
                    "result": cached,
                    "events": [],
                    "duration_ms": 0,
                    "from_cache": True,
                }
        
        # 执行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                self._run_skill_async(skill_name, params)
            )
        finally:
            loop.close()
        
        # 计算耗时
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        # 保存记录
        if self.auto_save and result["status"] == "success":
            record = ExecutionRecord(
                skill_name=skill_name,
                status=result["status"],
                params=params,
                result=result.get("result"),
                duration_ms=duration_ms,
            )
            self.state.save_record(record)
            
            # 缓存结果
            self.state.cache_result(skill_name, result.get("result"))
        
        result["duration_ms"] = duration_ms
        result["events"] = self._current_execution_events
        
        return result
    
    async def _run_skill_async(
        self,
        skill_name: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """异步执行 skill"""
        final_result = None
        final_status = "success"
        
        try:
            async for event in self.executor.run_skill(skill_name, params):
                if event.status == ExecutionStatus.SUCCESS and event.result is not None:
                    final_result = event.result
        except Exception as e:
            final_status = "failed"
            logger.error(f"执行失败: {e}")
        
        return {
            "status": final_status,
            "result": final_result,
        }
    
    def run_skill_chain(
        self,
        skill_names: List[str],
        params: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        链式执行多个 skills（同步）
        
        Returns:
            {
                "status": "success" | "failed",
                "results": {skill_name: result, ...},
                "events": [ExecutionEvent...],
                "duration_ms": ...
            }
        """
        start_time = datetime.now()
        self._current_execution_events.clear()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(
                self._run_skill_chain_async(skill_names, params)
            )
        finally:
            loop.close()
        
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        # 保存链执行记录
        if self.auto_save:
            for skill_name, result in results.items():
                if result is not None:
                    record = ExecutionRecord(
                        skill_name=skill_name,
                        status="success",
                        params=params,
                        result=result,
                        duration_ms=duration_ms,
                    )
                    self.state.save_record(record)
        
        return {
            "status": "success" if results else "failed",
            "results": results,
            "events": self._current_execution_events,
            "duration_ms": duration_ms,
        }
    
    async def _run_skill_chain_async(
        self,
        skill_names: List[str],
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """异步链式执行"""
        results = {}
        
        try:
            async for event in self.executor.run_skill_chain(skill_names, params):
                if event.status == ExecutionStatus.SUCCESS and event.result is not None:
                    results[event.skill_name] = event.result
        except Exception as e:
            logger.error(f"链执行失败: {e}")
        
        return results
    
    def get_execution_history(
        self,
        skill_name: str = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """获取执行历史"""
        records = self.state.get_latest_records(skill_name, limit)
        return [r.to_dict() for r in records]
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.state.get_statistics()
    
    def _on_execution_event(self, event: ExecutionEvent):
        """事件回调"""
        self._events.append(event)
        self._current_execution_events.append(event)


# ──────────────────────────────────────────────────────────────────
# CLI 接口
# ──────────────────────────────────────────────────────────────────

def print_skill_info(harness: SkillHarness):
    """打印所有 skills 信息"""
    skills = harness.discover_skills()
    
    if not skills:
        print("未发现任何 skills")
        return
    
    print(f"\n{'═'*80}")
    print(f"{'发现的 Skills':^80}")
    print(f"{'═'*80}\n")
    
    for skill in skills:
        print(f"📦 {skill['name']} (v{skill['version']})")
        print(f"   {skill['description']}")
        
        if skill['dependencies']:
            print(f"   依赖: {', '.join(skill['dependencies'])}")
        
        if skill['parameters']:
            print(f"   参数:")
            for param in skill['parameters']:
                required = "必需" if param['required'] else "可选"
                default = f" = {param['default']}" if param['default'] is not None else ""
                print(f"      - {param['name']} ({param['type']}) [{required}]{default}")
        
        print()


def print_execution_result(result: Dict[str, Any]):
    """打印执行结果"""
    print(f"\n{'─'*80}")
    print(f"{'执行结果':^80}")
    print(f"{'─'*80}\n")
    
    status = result['status']
    status_icon = "✅" if status == "success" else "❌"
    print(f"{status_icon} 状态: {status}")
    print(f"⏱️  耗时: {result['duration_ms']}ms")
    
    if result.get('from_cache'):
        print(f"💾 数据来源: 缓存")
    
    if result.get('result') is not None:
        print(f"📤 结果:")
        result_str = json.dumps(
            result['result'],
            ensure_ascii=False,
            indent=2,
        )
        for line in result_str.split('\n'):
            print(f"   {line}")
    
    if result.get('events'):
        print(f"\n📋 执行事件 ({len(result['events'])} 条):")
        for event in result['events']:
            icon = {
                "success": "✓",
                "failed": "✗",
                "pending": "·",
                "running": "→",
                "skipped": "∅",
            }.get(event.status.value, "?")
            
            print(f"   {icon} [{event.stage}] {event.skill_name}: {event.message}")
            if event.error:
                print(f"      错误: {event.error}")


def print_execution_chain_result(result: Dict[str, Any]):
    """打印链执行结果"""
    print(f"\n{'─'*80}")
    print(f"{'链执行结果':^80}")
    print(f"{'─'*80}\n")
    
    status = result['status']
    status_icon = "✅" if status == "success" else "❌"
    print(f"{status_icon} 状态: {status}")
    print(f"⏱️  总耗时: {result['duration_ms']}ms")
    
    if result['results']:
        print(f"\n📤 执行结果 ({len(result['results'])} 个):")
        for skill_name, res in result['results'].items():
            res_str = json.dumps(res, ensure_ascii=False)[:60]
            print(f"   • {skill_name}: {res_str}...")
    
    if result.get('events'):
        print(f"\n📋 执行事件 ({len(result['events'])} 条):")
        for event in result['events']:
            icon = {
                "success": "✓",
                "failed": "✗",
                "pending": "·",
                "running": "→",
                "skipped": "∅",
            }.get(event.status.value, "?")
            
            stage_short = event.stage[:4]
            print(f"   {icon} [{stage_short}] {event.skill_name}: {event.message}")


def print_statistics(harness: SkillHarness):
    """打印统计信息"""
    stats = harness.get_statistics()
    
    print(f"\n{'─'*80}")
    print(f"{'执行统计':^80}")
    print(f"{'─'*80}\n")
    
    print(f"总记录数: {stats['total_records']}")
    print(f"缓存大小: {stats['cache_size']}")
    print(f"快照数: {stats['snapshots_count']}")
    
    if stats['status_counts']:
        print(f"\n按状态统计:")
        for status, count in stats['status_counts'].items():
            print(f"  {status}: {count}")
    
    if stats['skill_counts']:
        print(f"\n按 Skill 统计:")
        for skill_name, count in sorted(
            stats['skill_counts'].items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]:
            print(f"  {skill_name}: {count}")


def main_cli():
    """CLI 主程序"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Skill Harness - 渐进式 Skills 加载执行框架",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="命令")
    
    # discover 命令
    subparsers.add_parser("discover", help="发现所有 skills")
    
    # run 命令
    run_parser = subparsers.add_parser("run", help="执行单个 skill")
    run_parser.add_argument("skill_name", help="Skill 名称")
    run_parser.add_argument(
        "-p", "--params",
        type=json.loads,
        default={},
        help="JSON 格式的输入参数",
    )
    run_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="不使用缓存",
    )
    
    # chain 命令
    chain_parser = subparsers.add_parser("chain", help="链式执行多个 skills")
    chain_parser.add_argument(
        "skills",
        help="Skill 名称列表，用逗号分隔",
    )
    chain_parser.add_argument(
        "-p", "--params",
        type=json.loads,
        default={},
        help="JSON 格式的输入参数",
    )
    
    # history 命令
    history_parser = subparsers.add_parser("history", help="查看执行历史")
    history_parser.add_argument(
        "-s", "--skill",
        help="过滤特定 skill",
    )
    history_parser.add_argument(
        "-l", "--limit",
        type=int,
        default=10,
        help="返回数量限制",
    )
    
    # stats 命令
    subparsers.add_parser("stats", help="查看统计信息")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # 初始化 harness
    harness = SkillHarness()
    harness.initialize()
    
    # 执行命令
    if args.command == "discover":
        print_skill_info(harness)
    
    elif args.command == "run":
        use_cache = not args.no_cache
        result = harness.run_skill(
            args.skill_name,
            params=args.params,
            use_cache=use_cache,
        )
        print_execution_result(result)
    
    elif args.command == "chain":
        skill_names = [s.strip() for s in args.skills.split(",")]
        result = harness.run_skill_chain(skill_names, params=args.params)
        print_execution_chain_result(result)
    
    elif args.command == "history":
        records = harness.get_execution_history(args.skill, args.limit)
        
        print(f"\n{'─'*80}")
        print(f"{'执行历史':^80}")
        print(f"{'─'*80}\n")
        
        for record in records:
            status_icon = "✓" if record['status'] == "success" else "✗"
            print(
                f"{status_icon} {record['skill_name']} "
                f"({record['timestamp']}) "
                f"耗时 {record['duration_ms']}ms"
            )
    
    elif args.command == "stats":
        print_statistics(harness)


if __name__ == "__main__":
    main_cli()
