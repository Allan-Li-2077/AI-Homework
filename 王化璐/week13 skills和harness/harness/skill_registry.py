"""
SkillRegistry - Skill发现与注册

渐进式加载第一阶段:
- 扫描skills目录，仅解析SKILL.md的frontmatter元数据（name/description/version）
- 不加载完整内容、references、scripts——轻量级注册
- 支持动态热加载（新增skill时自动发现）

教学重点:
1. frontmatter解析（YAML头）
2. 目录扫描与Skill发现
3. 元数据索引与快速检索
"""

import os
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillMeta:
    """Skill元数据（仅frontmatter，轻量级）"""
    name: str                          # skill名称（唯一标识）
    description: str                   # skill描述（用于匹配）
    version: str = "0.0.0"            # 版本号
    skill_dir: Path = Path()           # skill目录路径
    skill_md_path: Path = Path()       # SKILL.md文件路径
    registered_at: float = 0.0        # 注册时间戳
    
    @property
    def has_scripts(self) -> bool:
        """是否包含scripts目录"""
        return (self.skill_dir / "scripts").is_dir()
    
    @property
    def has_references(self) -> bool:
        """是否包含references目录"""
        return (self.skill_dir / "references").is_dir()
    
    @property
    def has_data(self) -> bool:
        """是否包含data目录"""
        return (self.skill_dir / "data").is_dir()
    
    def get_script_files(self) -> list[Path]:
        """获取所有脚本文件"""
        scripts_dir = self.skill_dir / "scripts"
        if not scripts_dir.is_dir():
            return []
        return sorted([
            f for f in scripts_dir.iterdir()
            if f.is_file() and f.suffix in (".py", ".ts", ".js", ".sh", ".bat")
        ])
    
    def get_reference_files(self) -> list[Path]:
        """获取所有参考文件"""
        refs_dir = self.skill_dir / "references"
        if not refs_dir.is_dir():
            return []
        return sorted([f for f in refs_dir.iterdir() if f.is_file()])


class SkillRegistry:
    """
    Skill注册表 - 渐进式加载第一阶段
    
    只加载SKILL.md的frontmatter元数据，不加载完整内容。
    这是轻量级注册，用于快速发现和匹配skills。
    """
    
    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, SkillMeta] = {}
        self._scan_timestamp: float = 0.0
        self._scan()
    
    def _scan(self):
        """扫描skills目录，发现所有skill"""
        import time
        self._skills.clear()
        
        if not self.skills_dir.is_dir():
            logger.warning(f"Skills目录不存在: {self.skills_dir}")
            return
        
        for item in self.skills_dir.iterdir():
            if not item.is_dir():
                continue
            
            skill_md = item / "SKILL.md"
            if not skill_md.is_file():
                logger.debug(f"跳过无SKILL.md的目录: {item}")
                continue
            
            meta = self._parse_frontmatter(skill_md)
            if meta:
                self._skills[meta.name] = meta
                logger.info(f"发现Skill: {meta.name} v{meta.version} -> {item}")
        
        self._scan_timestamp = time.time()
        logger.info(f"扫描完成，共发现 {len(self._skills)} 个Skills")
    
    def _parse_frontmatter(self, skill_md_path: Path) -> Optional[SkillMeta]:
        """
        解析SKILL.md的frontmatter（YAML头）
        
        支持格式:
        ---
        name: skill-name
        description: 单行描述
        version: 1.0.0
        ---
        
        多行描述:
        ---
        name: skill-name
        description: >-
          第一行描述
          第二行描述
        version: 1.0.0
        ---
        """
        try:
            content = skill_md_path.read_text(encoding="utf-8")
            
            # 匹配frontmatter区块
            pattern = r"^---\s*\n(.*?)\n---"
            match = re.match(pattern, content, re.DOTALL)
            
            if not match:
                logger.warning(f"SKILL.md缺少frontmatter: {skill_md_path}")
                return None
            
            frontmatter = match.group(1)
            data = {}
            
            # 解析frontmatter，支持多行值
            lines = frontmatter.splitlines()
            current_key = None
            current_value_lines = []
            in_multiline = False
            
            for line in lines:
                stripped = line.strip()
                
                # 跳过空行和注释
                if not stripped or stripped.startswith("#"):
                    if in_multiline and stripped:
                        current_value_lines.append(stripped)
                    continue
                
                # 检查是否是新键值对
                kv_match = re.match(r'^(\w[\w-]*)\s*:\s*(.*)', stripped)
                if kv_match and not in_multiline:
                    # 保存之前的键值对
                    if current_key:
                        data[current_key] = self._clean_value(" ".join(current_value_lines))
                    
                    key = kv_match.group(1)
                    value = kv_match.group(2).strip()
                    
                    # 检查是否是多行值开始（>- 或 |-）
                    if value in (">", "|-", "|", ">-"):
                        current_key = key
                        current_value_lines = []
                        in_multiline = True
                    else:
                        # 单行值
                        data[key] = self._clean_value(value)
                        current_key = None
                        current_value_lines = []
                        in_multiline = False
                elif in_multiline:
                    # 多行值的延续
                    # 检查是否遇到新的键值对
                    kv_check = re.match(r'^(\w[\w-]*)\s*:\s*(.*)', stripped)
                    if kv_check:
                        # 保存当前多行值
                        data[current_key] = self._clean_value(" ".join(current_value_lines))
                        # 开始新的键值对
                        key = kv_check.group(1)
                        value = kv_check.group(2).strip()
                        if value in (">", "|-", "|", ">-"):
                            current_key = key
                            current_value_lines = []
                            in_multiline = True
                        else:
                            data[key] = self._clean_value(value)
                            current_key = None
                            current_value_lines = []
                            in_multiline = False
                    else:
                        # 继续多行值
                        current_value_lines.append(stripped)
            
            # 保存最后一个键值对
            if current_key:
                data[current_key] = self._clean_value(" ".join(current_value_lines))
            
            name = data.get("name", skill_md_path.parent.name)
            description = data.get("description", "")
            
            # 如果还是空的，尝试用正则提取
            if not description and "description:" in frontmatter:
                desc_match = re.search(
                    r'description:\s*(.+?)(?:\n\w+:|$)',
                    frontmatter, re.DOTALL
                )
                if desc_match:
                    description = desc_match.group(1).strip()
            
            if not description:
                description = "(无描述)"
            
            return SkillMeta(
                name=name,
                description=description,
                version=data.get("version", "0.0.0"),
                skill_dir=skill_md_path.parent,
                skill_md_path=skill_md_path,
                registered_at=self._scan_timestamp,
            )
        except Exception as e:
            logger.error(f"解析SKILL.md失败 {skill_md_path}: {e}")
            return None
    
    @staticmethod
    def _clean_value(value: str) -> str:
        """清理值：去除引号和特殊字符"""
        value = value.strip()
        # 去除引号
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        # 去除多行标记（注意：- 必须放在字符类末尾或转义）
        value = re.sub(r'^[>|]+\s*', '', value)
        # 单独处理 - 前缀
        value = re.sub(r'^-\s*', '', value)
        return value.strip()
    
    def reload(self):
        """重新扫描skills目录（热加载）"""
        logger.info("重新扫描skills目录...")
        self._scan()
    
    def get_skill(self, name: str) -> Optional[SkillMeta]:
        """获取指定skill的元数据"""
        return self._skills.get(name)
    
    def list_skills(self) -> list[SkillMeta]:
        """列出所有已注册的skills"""
        return sorted(self._skills.values(), key=lambda s: s.name)
    
    def search_by_keyword(self, keyword: str) -> list[SkillMeta]:
        """按关键词搜索skills（匹配name和description）"""
        keyword_lower = keyword.lower()
        results = []
        for skill in self._skills.values():
            if (keyword_lower in skill.name.lower() or
                keyword_lower in skill.description.lower()):
                results.append(skill)
        return results
    
    def get_all_names(self) -> list[str]:
        """获取所有skill名称"""
        return sorted(self._skills.keys())
    
    @property
    def count(self) -> int:
        """已注册的skill数量"""
        return len(self._skills)
    
    def __len__(self) -> int:
        return len(self._skills)
    
    def __contains__(self, name: str) -> bool:
        return name in self._skills
    
    def __iter__(self):
        return iter(self._skills.values())
