"""
Harness - 渐进式加载执行Skills的编排器

整合SkillRegistry + SkillLoader + SkillMatcher + SkillExecutor:
1. 启动时扫描skills目录，注册所有skill元数据（轻量级）
2. 用户输入时，匹配最合适的skill（渐进式匹配）
3. 匹配成功后，按需加载skill完整内容（渐进式加载）
4. 按流程逐步执行skill（渐进式执行）
5. 每步产生进度事件，支持实时反馈

教学重点:
1. 渐进式加载的三个阶段
2. 事件驱动的架构
3. 可观测性（进度、日志）
"""

import os
import re
import sys
import json
import time
import logging
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable
from datetime import datetime

from .skill_registry import SkillRegistry, SkillMeta
from .skill_loader import SkillLoader, SkillContent
from .skill_matcher import SkillMatcher, MatchResult
from .skill_executor import SkillExecutor, ExecutionResult, StepResult

logger = logging.getLogger(__name__)


@dataclass
class HarnessEvent:
    """Harness事件 - 用于进度追踪和日志"""
    event_type: str               # 事件类型
    timestamp: float = 0.0        # 事件时间
    data: dict = field(default_factory=dict)  # 事件数据
    message: str = ""             # 可读消息
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        if not self.message:
            self.message = self._generate_message()
    
    def _generate_message(self) -> str:
        messages = {
            "scan_start": "开始扫描skills目录...",
            "scan_complete": f"扫描完成，发现 {self.data.get('count', 0)} 个skills",
            "skill_found": f"发现Skill: {self.data.get('name', 'unknown')}",
            "match_start": f"开始匹配: {self.data.get('input', '')[:50]}...",
            "match_complete": f"匹配完成: 置信度 {self.data.get('confidence', 0):.0%}",
            "match_miss": "未匹配到任何Skill",
            "load_start": f"开始加载Skill: {self.data.get('name', '')}",
            "load_complete": f"Skill加载完成: {self.data.get('name', '')}",
            "execute_start": f"开始执行Skill: {self.data.get('name', '')}",
            "execute_step": f"执行步骤 {self.data.get('step', 0)}",
            "execute_complete": f"执行完成: {'成功' if self.data.get('success') else '失败'}",
            "execute_error": f"执行错误: {self.data.get('error', '')}",
            "progress": f"进度: {self.data.get('progress', 0):.0f}%",
            "command": f"执行命令: {self.data.get('command', '')}",
        }
        return messages.get(self.event_type, self.event_type)
    
    def to_dict(self) -> dict:
        return {
            "type": self.event_type,
            "timestamp": self.timestamp,
            "data": self.data,
            "message": self.message,
        }


class Harness:
    """
    渐进式加载执行Skills的Harness编排器
    
    三大渐进阶段:
    1. 注册阶段: 启动时扫描SKILL.md frontmatter（轻量级）
    2. 匹配阶段: 用户输入后用description做关键词/正则初筛
    3. 执行阶段: 按SKILL.md流程逐步执行，按需加载资源
    """
    
    def __init__(
        self,
        skills_dir: str | Path,
        work_dir: Optional[str | Path] = None,
        auto_load: bool = False,
        use_llm_match: bool = False,
        event_callback: Optional[Callable[[HarnessEvent], None]] = None,
        verbose: bool = False,
    ):
        """
        Args:
            skills_dir: skills目录路径
            work_dir: 工作目录（输出文件存放位置）
            auto_load: 是否在加载SKILL.md时自动加载scripts和references
            use_llm_match: 是否使用LLM进行意图匹配
            event_callback: 事件回调函数
            verbose: 是否显示详细日志
        """
        self.skills_dir = Path(skills_dir)
        self.work_dir = Path(work_dir) if work_dir else Path.cwd()
        self.auto_load = auto_load
        self.use_llm_match = use_llm_match
        self.event_callback = event_callback
        self.verbose = verbose
        
        # 设置日志
        log_level = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%H:%M:%S',
        )
        
        # 核心组件初始化（渐进式注册）
        self.registry = SkillRegistry(self.skills_dir)
        self.loader = SkillLoader(auto_load=auto_load)
        self.matcher = SkillMatcher(self.registry, self.loader, use_llm=use_llm_match)
        self.executor = SkillExecutor(
            work_dir=self.work_dir,
            on_step_start=self._on_step_start,
            on_step_complete=self._on_step_complete,
            on_progress=self._on_progress,
        )
        
        # 统计
        self._event_count = 0
        self._match_count = 0
        self._execute_count = 0
        
        # 触发初始化事件
        self._emit(HarnessEvent(
            event_type="scan_complete",
            data={"count": self.registry.count},
        ))
        
        logger.info(f"Harness初始化完成: {self.registry.count} 个Skills可用")
    
    # ── 核心API ──────────────────────────────────────────────────────────
    
    def process(self, user_input: str, params: Optional[dict] = None) -> dict:
        """
        处理用户输入：匹配 → 加载 → 执行
        
        这是Harness的主入口，实现完整的渐进式流程。
        """
        start_time = time.time()
        result = {
            "success": False,
            "input": user_input,
            "matched_skill": None,
            "load_time_ms": 0,
            "execute_time_ms": 0,
            "total_time_ms": 0,
            "match_result": None,
            "execution_result": None,
            "output": "",
            "errors": [],
            "steps": [],
        }
        
        try:
            # Stage 1: 匹配
            self._emit(HarnessEvent(
                event_type="match_start",
                data={"input": user_input},
            ))
            
            match_result = self.matcher.match(user_input)
            self._match_count += 1
            
            if not match_result:
                self._emit(HarnessEvent(event_type="match_miss"))
                result["errors"].append("未匹配到任何Skill")
                result["output"] = self._generate_fallback_response(user_input)
                result["total_time_ms"] = (time.time() - start_time) * 1000
                return result
            
            self._emit(HarnessEvent(
                event_type="match_complete",
                data={
                    "skill": match_result.skill_name,
                    "confidence": match_result.confidence,
                },
            ))
            
            result["matched_skill"] = match_result.skill_name
            result["match_result"] = match_result
            
            # Stage 2: 加载（渐进式）
            meta = self.registry.get_skill(match_result.skill_name)
            if not meta:
                result["errors"].append(f"Skill not found: {match_result.skill_name}")
                result["total_time_ms"] = (time.time() - start_time) * 1000
                return result
            
            load_start = time.time()
            self._emit(HarnessEvent(
                event_type="load_start",
                data={"name": meta.name},
            ))
            
            content = self.loader.load(meta)
            
            load_time = (time.time() - load_start) * 1000
            result["load_time_ms"] = load_time
            
            self._emit(HarnessEvent(
                event_type="load_complete",
                data={"name": meta.name, "duration_ms": load_time},
            ))
            
            # Stage 3: 执行（渐进式）
            self._emit(HarnessEvent(
                event_type="execute_start",
                data={"name": content.name},
            ))
            
            exec_result = self.executor.execute(content, user_input, params)
            self._execute_count += 1
            
            result["execution_result"] = exec_result
            result["execute_time_ms"] = exec_result.total_duration_ms
            result["output"] = exec_result.final_output
            result["success"] = exec_result.success
            result["steps"] = [s.__dict__ for s in exec_result.steps]
            
            if exec_result.errors:
                result["errors"].extend(exec_result.errors)
            
            self._emit(HarnessEvent(
                event_type="execute_complete",
                data={
                    "name": content.name,
                    "success": exec_result.success,
                    "duration_ms": exec_result.total_duration_ms,
                },
            ))
            
        except Exception as e:
            logger.error(f"处理异常: {e}", exc_info=True)
            result["errors"].append(str(e))
            result["output"] = f"处理异常: {e}"
        
        result["total_time_ms"] = (time.time() - start_time) * 1000
        return result
    
    def process_all(self, user_input: str, top_k: int = 3) -> list[dict]:
        """
        处理用户输入，尝试所有可能的Skills
        
        返回top-k个最匹配的skill执行结果。
        """
        matches = self.matcher.match_all(user_input, top_k=top_k)
        results = []
        
        for match in matches:
            # 为每个匹配的skill尝试执行
            logger.info(f"尝试执行Skill: {match.skill_name} (置信度: {match.confidence})")
            
            # 创建临时registry和loader
            meta = self.registry.get_skill(match.skill_name)
            if not meta:
                continue
            
            # 加载并执行
            content = self.loader.load(meta)
            exec_result = self.executor.execute(content, user_input)
            
            result = {
                "skill_name": match.skill_name,
                "confidence": match.confidence,
                "execution_result": exec_result,
                "success": exec_result.success,
                "output": exec_result.final_output,
            }
            results.append(result)
        
        return results
    
    def reload_skills(self):
        """重新扫描skills目录"""
        self.registry.reload()
        self.loader.invalidate_all()
        
        self._emit(HarnessEvent(
            event_type="scan_complete",
            data={"count": self.registry.count, "reloaded": True},
        ))
        
        logger.info(f"Skills已重新加载: {self.registry.count} 个")
    
    # ── 查询API ──────────────────────────────────────────────────────────
    
    def list_skills(self) -> list[dict]:
        """列出所有可用的Skills"""
        skills = self.registry.list_skills()
        return [
            {
                "name": s.name,
                "description": s.description[:100],
                "version": s.version,
                "has_scripts": s.has_scripts,
                "has_references": s.has_references,
                "has_data": s.has_data,
                "script_count": len(s.get_script_files()),
            }
            for s in skills
        ]
    
    def get_skill_info(self, name: str) -> Optional[dict]:
        """获取指定Skill的详细信息"""
        meta = self.registry.get_skill(name)
        if not meta:
            return None
        
        # 加载内容
        content = self.loader.load(meta)
        
        return {
            "meta": {
                "name": meta.name,
                "description": meta.description,
                "version": meta.version,
                "skill_dir": str(meta.skill_dir),
            },
            "content": {
                "intro_text_length": len(content.intro_text),
                "trigger_scenarios": content.trigger_scenarios,
                "execution_flow": [
                    {
                        "index": s.index,
                        "description": s.description,
                        "action_type": s.action_type,
                    }
                    for s in content.execution_flow
                ],
                "output_rules": content.output_rules,
                "notes": content.notes,
            },
            "resources": {
                "scripts": [{"name": n, "size": len(c)} for n, c in content._scripts],
                "references": [{"name": n, "size": len(c)} for n, c in content._references],
                "data_files": [{"name": n, "size": len(c)} for n, c in content._data_files],
            },
        }
    
    def search_skills(self, keyword: str) -> list[dict]:
        """搜索Skills"""
        skills = self.registry.search_by_keyword(keyword)
        return [
            {
                "name": s.name,
                "description": s.description[:80],
            }
            for s in skills
        ]
    
    # ── 事件回调 ──────────────────────────────────────────────────────────
    
    def _emit(self, event: HarnessEvent):
        """发送事件"""
        self._event_count += 1
        
        if self.verbose:
            logger.debug(f"[Harness Event] {event.event_type}: {event.message}")
        
        if self.event_callback:
            try:
                self.event_callback(event)
            except Exception as e:
                logger.error(f"事件回调失败: {e}")
    
    def _on_step_start(self, step_index: int, description: str):
        """步骤开始回调"""
        self._emit(HarnessEvent(
            event_type="execute_step",
            data={
                "step": step_index,
                "description": description[:50],
                "status": "start",
            },
            message=f"Step {step_index}: {description[:50]}",
        ))
    
    def _on_step_complete(self, step_index: int, result: StepResult):
        """步骤完成回调"""
        self._emit(HarnessEvent(
            event_type="execute_step",
            data={
                "step": step_index,
                "success": result.success,
                "duration_ms": result.duration_ms,
                "status": "complete",
            },
            message=f"Step {step_index}: {'✓' if result.success else '✗'} ({result.duration_ms:.0f}ms)",
        ))
    
    def _on_progress(self, progress: float, message: str):
        """进度回调"""
        self._emit(HarnessEvent(
            event_type="progress",
            data={
                "progress": progress,
                "message": message,
            },
        ))
    
    # ── 辅助方法 ──────────────────────────────────────────────────────────
    
    def _generate_fallback_response(self, user_input: str) -> str:
        """未匹配到skill时的回退响应"""
        skills_list = self.registry.get_all_names()
        skills_str = "、".join(skills_list) if skills_list else "（暂无可用Skills）"
        
        return (
            f"抱歉，未能匹配到合适的Skill。\n\n"
            f"当前可用的Skills: {skills_str}\n\n"
            f"你可以尝试:\n"
            f"1. 使用list命令查看所有可用Skills\n"
            f"2. 用更明确的指令描述你想要的操作\n"
            f"3. 输入help查看使用说明"
        )
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "skills_count": self.registry.count,
            "cached_skills": self.loader.cache_size,
            "total_events": self._event_count,
            "total_matches": self._match_count,
            "total_executions": self._execute_count,
            "loader_load_count": self.loader.loaded_count,
        }
    
    def clear_cache(self):
        """清除所有缓存"""
        self.loader.invalidate_all()
        logger.info("缓存已清除")
    
    def list_skills_display(self, colors: dict):
        """列出所有可用Skills（带彩色输出）"""
        skills = self.list_skills()
        c = colors
        
        print(f"\n{c['bold']}可用Skills:{c['reset']}")
        print(f"{c['cyan']}{'─'*50}{c['reset']}")
        
        if not skills:
            print(f"  {c['yellow']}（暂无可用Skills）{c['reset']}")
        else:
            for s in skills:
                print(f"  {c['green']}●{c['reset']} {c['bold']}{s['name']}{c['reset']} v{s['version']}")
                print(f"    {s['description'][:70]}")
                if s['has_scripts']:
                    print(f"    {c['magenta']}脚本: {s['script_count']} 个{c['reset']}")
        
        print(f"{c['cyan']}{'─'*50}{c['reset']}\n")


# ── CLI入口 ──────────────────────────────────────────────────────────────────

def run_cli():
    """命令行接口"""
    parser = argparse.ArgumentParser(
        description="渐进式加载执行Skills的Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
交互模式命令:
  list          列出所有可用Skills
  search <关键词>  搜索Skills
  info <skill>   查看Skill详细信息
  stats         查看统计信息
  reload        重新加载Skills
  clear         清除缓存
  quit/exit     退出

示例:
  python harness.py                    # 启动交互模式
  python harness.py --skills ./skills  # 指定skills目录
  python harness.py -q "给我做张flash卡"  # 单次执行
        """,
    )
    
    parser.add_argument(
        "--skills", "-s",
        default=str(Path(__file__).parent.parent / "skills"),
        help="Skills目录路径 (默认: ./skills)",
    )
    parser.add_argument(
        "--work-dir", "-w",
        default=str(Path.cwd() / "outputs"),
        help="工作目录 (默认: ./outputs)",
    )
    parser.add_argument(
        "--query", "-q",
        help="单次执行模式: 直接执行查询并退出",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细日志",
    )
    parser.add_argument(
        "--auto-load",
        action="store_true",
        help="自动加载scripts和references",
    )
    
    args = parser.parse_args()
    
    # 创建事件回调（彩色控制台输出）
    colors = {
        "reset": "\033[0m",
        "cyan": "\033[36m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "magenta": "\033[35m",
        "blue": "\033[34m",
        "bold": "\033[1m",
    }
    
    def console_callback(event: HarnessEvent):
        t = event.event_type
        c = colors
        
        if t == "scan_complete":
            count = event.data.get("count", 0)
            print(f"\n{c['cyan']}{'═'*50}{c['reset']}")
            print(f"{c['cyan']}  Harness就绪{c['reset']}")
            print(f"{c['cyan']}  发现 {c['bold']}{count}{c['reset']}{c['cyan']} 个Skills{c['reset']}")
            print(f"{c['cyan']}{'═'*50}{c['reset']}\n")
        
        elif t == "match_complete":
            skill = event.data.get("skill", "")
            conf = event.data.get("confidence", 0)
            print(f"  {c['blue']}→{c['reset']} 匹配: {c['bold']}{skill}{c['reset']} ({conf:.0%})")
        
        elif t == "match_miss":
            print(f"  {c['yellow']}→{c['reset']} 未匹配到Skill")
        
        elif t == "execute_step":
            if event.data.get("status") == "start":
                step = event.data.get("step", 0)
                print(f"  {c['magenta']}◇{c['reset']} 步骤 {step}...", end=" ", flush=True)
            else:
                success = event.data.get("success", False)
                duration = event.data.get("duration_ms", 0)
                icon = f"{c['green']}✓{c['reset']}" if success else f"{c['yellow']}✗{c['reset']}"
                print(f"{icon} ({duration:.0f}ms)")
        
        elif t == "execute_complete":
            success = event.data.get("success", False)
            duration = event.data.get("duration_ms", 0)
            status = f"{c['green']}成功{c['reset']}" if success else f"{c['yellow']}失败{c['reset']}"
            print(f"  {c['green']}━━{c['reset']} 执行{status} ({duration:.0f}ms)\n")
        
        elif t == "load_complete":
            name = event.data.get("name", "")
            duration = event.data.get("duration_ms", 0)
            print(f"  {c['blue']}↓{c['reset']} 加载 {name} ({duration:.0f}ms)")
    
    # 创建Harness实例
    harness = Harness(
        skills_dir=args.skills,
        work_dir=args.work_dir,
        auto_load=args.auto_load,
        verbose=args.verbose,
        event_callback=console_callback,
    )
    
    # 单次执行模式
    if args.query:
        print(f"\n{c('bold')}输入: {args.query}{c('reset')}\n")
        result = harness.process(args.query)
        _print_result(result, colors)
        return
    
    # 交互模式
    print(f"\n{c('bold')}渐进式加载执行Skills的Harness{c('reset')}")
    print(f"输入help查看使用说明，输入quit退出\n")
    
    harness.list_skills_display(colors)
    
    while True:
        try:
            user_input = input(f"{colors['bold']}你: {colors['reset']}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break
        
        if not user_input:
            continue
        
        lower_input = user_input.lower().strip()
        
        # 命令处理
        if lower_input in ("quit", "exit", "q"):
            print("再见！")
            break
        elif lower_input in ("help", "h", "?"):
            _print_help()
            continue
        elif lower_input == "list":
            harness.list_skills_display(colors)
            continue
        elif lower_input.startswith("search "):
            keyword = user_input[7:].strip()
            results = harness.search_skills(keyword)
            if results:
                for r in results:
                    print(f"  {c('bold')}{r['name']}{c('reset')}: {r['description'][:60]}")
            else:
                print(f"  未找到包含 '{keyword}' 的Skills")
            continue
        elif lower_input.startswith("info "):
            name = user_input[5:].strip()
            info = harness.get_skill_info(name)
            if info:
                print(f"\n{c('bold')}{'='*40}{c('reset')}")
                print(f"{c('bold')}Skill详情: {name}{c('reset')}")
                print(f"{c('bold')}{'='*40}{c('reset')}")
                print(f"  描述: {info['meta']['description'][:100]}")
                print(f"  版本: {info['meta']['version']}")
                if info['content']['execution_flow']:
                    print(f"\n  执行流程:")
                    for step in info['content']['execution_flow']:
                        print(f"    {step['index']}. {step['description'][:60]}")
                print()
            else:
                print(f"  Skill '{name}' 不存在")
            continue
        elif lower_input == "stats":
            stats = harness.get_stats()
            print(f"\n{c('bold')}统计信息{c('reset')}")
            for k, v in stats.items():
                print(f"  {k}: {v}")
            continue
        elif lower_input == "reload":
            harness.reload_skills()
            harness.list_skills_display(colors)
            continue
        elif lower_input == "clear":
            harness.clear_cache()
            print("  缓存已清除")
            continue
        
        # 正常处理
        print()
        result = harness.process(user_input)
        _print_result(result, colors)


def c(color_name: str) -> str:
    """颜色辅助函数"""
    colors = {
        "reset": "\033[0m",
        "cyan": "\033[36m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "magenta": "\033[35m",
        "blue": "\033[34m",
        "bold": "\033[1m",
    }
    return colors.get(color_name, "")


def _print_result(result: dict, colors: dict):
    """打印执行结果"""
    success = result.get("success", False)
    output = result.get("output", "")
    errors = result.get("errors", [])
    total_time = result.get("total_time_ms", 0)
    
    status_color = colors["green"] if success else colors["yellow"]
    status = "成功" if success else "失败"
    
    print(f"{colors['bold']}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{colors['reset']}")
    print(f"  {status_color}执行{status}{colors['reset']} | {colors['bold']}耗时{total_time:.0f}ms{colors['reset']}")
    print(f"{colors['bold']}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{colors['reset']}")
    
    if output:
        # 打印输出（截断过长内容）
        if len(output) > 500:
            output = output[:500] + "\n... (输出已截断)"
        print(f"\n{output}")
    
    if errors:
        print(f"\n{colors['yellow']}错误信息:{colors['reset']}")
        for err in errors:
            print(f"  • {err}")
    
    print()


def _print_help():
    """打印帮助信息"""
    print(f"""
{'-'*50}
{c('bold')}渐进式加载执行Skills的Harness{c('reset')}
{'-'*50}

{c('bold')}用法:{c('reset')}
  直接输入指令，Harness会自动匹配并执行对应的Skill

{c('bold')}命令:{c('reset')}
  list            列出所有可用Skills
  search <关键词>  搜索Skills
  info <skill>    查看Skill详细信息
  stats           查看统计信息
  reload          重新加载Skills
  clear           清除缓存
  help/h          显示此帮助
  quit/exit/q     退出

{c('bold')}示例:{c('reset')}
  给我做张flash卡
  画一个系统架构图
  帮我生成流程图
{'-'*50}
""")


if __name__ == "__main__":
    run_cli()
