"""
SkillLoader - 渐进式Skill内容加载

渐进式加载第二阶段:
- 只在需要时加载完整的SKILL.md正文、scripts、references
- 延迟加载：匹配成功后才加载skill完整内容
- 缓存已加载的内容，避免重复IO

教学重点:
1. 按需加载（Lazy Loading）
2. 内容缓存策略
3. SKILL.md正文解析（流程步骤提取）
"""

import re
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

from .skill_registry import SkillMeta

logger = logging.getLogger(__name__)


@dataclass
class SkillStep:
    """Skill执行步骤"""
    index: int                        # 步骤序号
    description: str                  # 步骤描述
    action_type: str = "text"         # 动作类型: text/script/read_file/write_file/run_command
    target: str = ""                  # 目标文件或命令
    is_optional: bool = False         # 是否可选步骤


@dataclass
class SkillContent:
    """Skill完整内容（按需加载）"""
    meta: SkillMeta                   # 元数据引用
    full_content: str = ""            # SKILL.md完整内容
    loaded_at: float = 0.0            # 加载时间戳
    load_complete: bool = False       # 是否已完全加载
    
    # 解析后的结构
    intro_text: str = ""              # 介绍文本（frontmatter之后）
    trigger_scenarios: list[str] = field(default_factory=list)  # 触发场景
    execution_flow: list[SkillStep] = field(default_factory=list)  # 执行流程步骤
    output_rules: list[str] = field(default_factory=list)        # 输出规则
    notes: list[str] = field(default_factory=list)               # 注意事项
    
    # 资源文件（按需加载）
    _scripts: list[tuple[str, str]] = field(default_factory=list)   # (filename, content)
    _references: list[tuple[str, str]] = field(default_factory=list) # (filename, content)
    _data_files: list[tuple[str, str]] = field(default_factory=list) # (filename, content)
    
    @property
    def name(self) -> str:
        return self.meta.name
    
    @property
    def skill_dir(self) -> Path:
        return self.meta.skill_dir
    
    def get_script_content(self, filename: str) -> Optional[str]:
        """获取脚本文件内容（按需加载）"""
        for name, content in self._scripts:
            if name == filename:
                return content
        return None
    
    def get_reference_content(self, filename: str) -> Optional[str]:
        """获取参考文件内容（按需加载）"""
        for name, content in self._references:
            if name == filename:
                return content
        return None
    
    def get_data_file_content(self, filename: str) -> Optional[str]:
        """获取数据文件内容"""
        for name, content in self._data_files:
            if name == filename:
                return content
        return None


class SkillLoader:
    """
    Skill内容加载器 - 渐进式加载第二阶段
    
    在SkillRegistry发现skill后，当需要执行时才加载完整内容。
    支持分步加载：先加载SKILL.md正文，再按需加载scripts/references。
    """
    
    def __init__(self, auto_load: bool = False):
        """
        Args:
            auto_load: 是否在加载SKILL.md时自动加载scripts和references
        """
        self._cache: dict[str, SkillContent] = {}
        self._auto_load = auto_load
        self._load_count = 0
    
    def load(self, meta: SkillMeta) -> SkillContent:
        """
        加载Skill完整内容（按需调用）
        
        这是渐进式加载的第二步：
        1. 加载SKILL.md完整内容
        2. 解析执行流程步骤
        3. （可选）加载scripts和references
        """
        import time
        
        # 检查缓存
        if meta.name in self._cache:
            cached = self._cache[meta.name]
            # 检查文件是否修改（简单检查mtime）
            if self._is_cache_valid(cached, meta):
                logger.debug(f"使用缓存: {meta.name}")
                return cached
        
        logger.info(f"加载Skill内容: {meta.name}")
        start_time = time.time()
        
        content = SkillContent(meta=meta, loaded_at=start_time)
        
        # Step 1: 加载SKILL.md完整内容
        self._load_skill_md(content)
        
        # Step 2: 解析内容结构
        self._parse_structure(content)
        
        # Step 3: （可选）加载资源文件
        if self._auto_load:
            self._load_scripts(content)
            self._load_references(content)
            self._load_data_files(content)
        
        content.load_complete = True
        self._cache[meta.name] = content
        self._load_count += 1
        
        elapsed = (time.time() - start_time) * 1000
        logger.info(f"Skill加载完成: {meta.name} ({elapsed:.1f}ms)")
        
        return content
    
    def load_scripts(self, content: SkillContent) -> SkillContent:
        """按需加载scripts目录"""
        if content._scripts:
            return content
        
        logger.debug(f"加载scripts: {content.name}")
        scripts_dir = content.skill_dir / "scripts"
        if scripts_dir.is_dir():
            for f in sorted(scripts_dir.iterdir()):
                if f.is_file():
                    try:
                        text = f.read_text(encoding="utf-8")
                        content._scripts.append((f.name, text))
                        logger.debug(f"  加载: {f.name} ({len(text)} 字符)")
                    except Exception as e:
                        logger.warning(f"  加载失败 {f.name}: {e}")
        
        return content
    
    def load_references(self, content: SkillContent) -> SkillContent:
        """按需加载references目录"""
        if content._references:
            return content
        
        logger.debug(f"加载references: {content.name}")
        refs_dir = content.skill_dir / "references"
        if refs_dir.is_dir():
            for f in sorted(refs_dir.iterdir()):
                if f.is_file():
                    try:
                        text = f.read_text(encoding="utf-8")
                        content._references.append((f.name, text))
                        logger.debug(f"  加载: {f.name} ({len(text)} 字符)")
                    except Exception as e:
                        logger.warning(f"  加载失败 {f.name}: {e}")
        
        return content
    
    def load_data_files(self, content: SkillContent) -> SkillContent:
        """按需加载data目录"""
        if content._data_files:
            return content
        
        logger.debug(f"加载data: {content.name}")
        data_dir = content.skill_dir / "data"
        if data_dir.is_dir():
            for f in sorted(data_dir.iterdir()):
                if f.is_file():
                    try:
                        text = f.read_text(encoding="utf-8")
                        content._data_files.append((f.name, text))
                        logger.debug(f"  加载: {f.name} ({len(text)} 字符)")
                    except Exception as e:
                        logger.warning(f"  加载失败 {f.name}: {e}")
        
        return content
    
    def _load_skill_md(self, content: SkillContent):
        """加载SKILL.md完整内容"""
        try:
            full_text = content.meta.skill_md_path.read_text(encoding="utf-8")
            content.full_content = full_text
            
            # 提取frontmatter之后的正文
            pattern = r"^---\s*\n.*?\n---\s*\n(.*)"
            match = re.match(pattern, full_text, re.DOTALL)
            if match:
                content.intro_text = match.group(1).strip()
            else:
                content.intro_text = full_text
        except Exception as e:
            logger.error(f"加载SKILL.md失败 {content.meta.name}: {e}")
    
    def _parse_structure(self, content: SkillContent):
        """解析SKILL.md的结构化内容"""
        text = content.intro_text
        
        # 解析触发场景
        trigger_section = self._extract_section(text, ["触发场景", "Trigger", "Use when"])
        if trigger_section:
            triggers = re.findall(r'[-*]\s*(.+)', trigger_section)
            content.trigger_scenarios = [t.strip() for t in triggers if t.strip()]
        
        # 解析执行流程
        flow_section = self._extract_section(text, ["执行流程", "执行步骤", "流程", "Process", "Flow", "Steps"])
        if flow_section:
            steps = self._parse_steps(flow_section)
            content.execution_flow = steps
        
        # 解析输出规则
        output_section = self._extract_section(text, ["输出规则", "输出", "Output", "Result"])
        if output_section:
            outputs = re.findall(r'[-*]\s*(.+)', output_section)
            content.output_rules = [o.strip() for o in outputs if o.strip()]
        
        # 解析注意事项
        notes_section = self._extract_section(text, ["注意事项", "Note", "Notes", "Attention", "Warning"])
        if notes_section:
            notes = re.findall(r'[-*]\s*(.+)', notes_section)
            content.notes = [n.strip() for n in notes if n.strip()]
    
    def _extract_section(self, text: str, headers: list[str]) -> Optional[str]:
        """提取指定标题下的段落"""
        lines = text.splitlines()
        result_lines = []
        in_section = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # 检查是否是目标标题
            for header in headers:
                if stripped.lower().startswith(f"# {header.lower()}") or stripped.lower() == f"## {header.lower()}":
                    in_section = True
                    break
            
            # 如果是新的标题（不是我们要的），停止
            if in_section and stripped.startswith("#") and not any(
                stripped.lower().startswith(f"# {h.lower()}") or stripped.lower() == f"## {h.lower()}"
                for h in headers
            ):
                break
            
            if in_section:
                result_lines.append(line)
        
        return "\n".join(result_lines).strip() if result_lines else None
    
    def _parse_steps(self, flow_text: str) -> list[SkillStep]:
        """解析执行步骤"""
        steps = []
        lines = flow_text.splitlines()
        current_step = None
        
        for line in lines:
            stripped = line.strip()
            
            # 匹配步骤编号: 1. 2. 3.
            step_match = re.match(r'^(\d+)[.、)\s]\s*(.+)', stripped)
            if step_match:
                if current_step:
                    steps.append(current_step)
                idx = int(step_match.group(1))
                desc = step_match.group(2).strip()
                current_step = SkillStep(
                    index=idx,
                    description=desc,
                    action_type=self._determine_action_type(desc),
                )
            elif stripped and current_step:
                # 步骤的补充内容
                current_step.description += " " + stripped
        
        if current_step:
            steps.append(current_step)
        
        return steps
    
    def _determine_action_type(self, description: str) -> str:
        """根据描述推断动作类型"""
        desc_lower = description.lower()
        
        if any(kw in desc_lower for kw in ["运行", "执行", "run", "execute", "python", "bun", "npm"]):
            return "run_command"
        elif any(kw in desc_lower for kw in ["读取", "阅读", "read", "load", "加载"]):
            return "read_file"
        elif any(kw in desc_lower for kw in ["保存", "写入", "保存", "write", "save", "output"]):
            return "write_file"
        elif any(kw in desc_lower for kw in ["生成", "创建", "生成", "create", "generate", "write"]):
            return "generate"
        return "text"
    
    def _is_cache_valid(self, cached: SkillContent, meta: SkillMeta) -> bool:
        """检查缓存是否有效"""
        try:
            current_mtime = meta.skill_md_path.stat().st_mtime
            return current_mtime <= cached.loaded_at
        except Exception:
            return False
    
    def invalidate(self, name: str):
        """失效指定skill的缓存"""
        if name in self._cache:
            del self._cache[name]
            logger.info(f"缓存已失效: {name}")
    
    def invalidate_all(self):
        """失效所有缓存"""
        self._cache.clear()
        logger.info("所有缓存已失效")
    
    def get_cached_names(self) -> list[str]:
        """获取已缓存的skill名称"""
        return list(self._cache.keys())
    
    @property
    def loaded_count(self) -> int:
        """累计加载次数"""
        return self._load_count
    
    @property
    def cache_size(self) -> int:
        """当前缓存数量"""
        return len(self._cache)
