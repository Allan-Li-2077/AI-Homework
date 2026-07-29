"""
Stage 1: Skill Discovery & Loading (技能发现与加载)

职责：
  1. 扫描 skills/ 目录，发现所有 skill 子目录
  2. 读取每个 skill 的 SKILL.md 元数据
  3. 构建 SkillRegistry（全局 skill 注册表）
  4. 验证元数据格式与依赖关系

设计理念（与 week13 对应）：
  - 类比 MemoryLoader：通过 Markdown 文件驱动发现
  - Skill 描述即 Markdown 配置，自文档化
  - 支持版本管理、依赖声明
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class SkillParameter:
    """Skill 参数定义"""
    name: str
    type: str  # "str", "int", "float", "bool", "list", "dict", "any"
    required: bool = False
    default: Any = None
    description: str = ""

    def validate(self, value: Any) -> bool:
        """参数类型检查"""
        if value is None:
            return not self.required
        
        type_map = {
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
        }
        
        if self.type == "any":
            return True
        
        expected_type = type_map.get(self.type)
        if expected_type:
            return isinstance(value, expected_type)
        return True


@dataclass
class SkillMetadata:
    """Skill 元数据（对应 SKILL.md 的 frontmatter）"""
    name: str
    version: str
    description: str
    trigger: str  # 触发条件描述
    dependencies: List[str]  # 依赖的其他 skill 名称
    parameters: List[SkillParameter]
    returns: Dict[str, str]  # {"type": "...", "description": "..."}
    skill_dir: Path = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], skill_dir: Path = None) -> "SkillMetadata":
        """从字典创建元数据"""
        params = []
        for p in data.get("parameters", []):
            if isinstance(p, dict):
                params.append(SkillParameter(**p))
            else:
                params.append(p)
        
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            trigger=data.get("trigger", ""),
            dependencies=data.get("dependencies", []),
            parameters=params,
            returns=data.get("returns", {"type": "any", "description": ""}),
            skill_dir=skill_dir,
        )


class SkillRegistry:
    """全局 Skill 注册表（类比 MemoryLoader 的四层加载机制）"""
    
    def __init__(self):
        self._skills: Dict[str, SkillMetadata] = {}
        self._loaded = False
    
    def register(self, metadata: SkillMetadata):
        """注册一个 skill 元数据"""
        self._skills[metadata.name] = metadata
        logger.debug(f"注册 skill: {metadata.name} v{metadata.version}")
    
    def get(self, name: str) -> Optional[SkillMetadata]:
        """获取 skill 元数据"""
        return self._skills.get(name)
    
    def list_skills(self) -> List[SkillMetadata]:
        """列出所有已注册的 skills"""
        return list(self._skills.values())
    
    def validate_dependencies(self) -> List[str]:
        """验证所有依赖关系，返回错误信息列表"""
        errors = []
        for name, meta in self._skills.items():
            for dep in meta.dependencies:
                if dep not in self._skills:
                    errors.append(f"Skill '{name}' 依赖未找到: '{dep}'")
        return errors
    
    def topological_sort(self, skill_names: List[str]) -> List[str]:
        """
        对指定的 skills 进行拓扑排序，返回执行顺序
        
        这对应 Memory Flush 的三步机制：
          Step 1: 依赖分析（图遍历）
          Step 2: 拓扑排序（执行顺序）
          Step 3: 逐个执行（依赖关系保证）
        """
        # 构建依赖图
        in_degree = {}
        graph = {}
        visited_set = set()
        
        def visit(name: str):
            if name in visited_set:
                return
            visited_set.add(name)
            if name not in self._skills:
                raise ValueError(f"Skill not found: {name}")
            
            meta = self._skills[name]
            graph[name] = meta.dependencies
            
            for dep in meta.dependencies:
                visit(dep)
        
        for name in skill_names:
            visit(name)
        
        # 计算入度
        for name in visited_set:
            in_degree[name] = 0
        
        for name in visited_set:
            for dep in graph.get(name, []):
                if dep in in_degree:
                    in_degree[dep] += 1
        
        # Kahn 算法
        queue = [name for name in visited_set if in_degree[name] == 0]
        sorted_list = []
        
        while queue:
            node = queue.pop(0)
            sorted_list.append(node)
            
            for name in visited_set:
                if node in graph.get(name, []):
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)
        
        if len(sorted_list) != len(visited_set):
            raise ValueError("Circular dependency detected")
        
        # 反向排序（依赖关系反向：应该先执行被依赖者）
        sorted_list.reverse()
        return sorted_list


class SkillLoader:
    """
    Skill 加载器（对应 MemoryLoader 的模式）
    
    职责：
      1. 扫描文件系统发现 skills
      2. 解析 SKILL.md frontmatter
      3. 动态加载 Python 实现模块
      4. 返回 SkillRegistry
    """
    
    def __init__(self, skills_dir: Path = None):
        self.skills_dir = skills_dir or Path(__file__).parent.parent / "skills"
        self.registry = SkillRegistry()
    
    def discover_and_load(self) -> SkillRegistry:
        """
        发现并加载所有 skills
        
        流程（类比 MemoryLoader.build_system_prompt）：
          1. 扫描 skills/ 目录
          2. 逐个读取 SKILL.md
          3. 解析 frontmatter
          4. 验证并注册
        """
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return self.registry
        
        skill_dirs = [d for d in self.skills_dir.iterdir() if d.is_dir()]
        logger.info(f"发现 {len(skill_dirs)} 个 skill 目录")
        
        for skill_dir in sorted(skill_dirs):
            try:
                self._load_skill(skill_dir)
            except Exception as e:
                logger.error(f"加载 skill {skill_dir.name} 失败: {e}")
        
        # 验证依赖关系
        errors = self.registry.validate_dependencies()
        for error in errors:
            logger.error(error)
        
        return self.registry
    
    def _load_skill(self, skill_dir: Path):
        """加载单个 skill"""
        skill_md_path = skill_dir / "SKILL.md"
        
        if not skill_md_path.exists():
            logger.warning(f"SKILL.md not found in {skill_dir}")
            return
        
        # 解析 SKILL.md
        metadata = self._parse_skill_md(skill_md_path, skill_dir)
        if metadata:
            self.registry.register(metadata)
    
    def _parse_skill_md(self, md_path: Path, skill_dir: Path) -> Optional[SkillMetadata]:
        """
        解析 SKILL.md 文件的 frontmatter
        
        格式：
        ---
        name: demo-greeting
        version: 1.0
        ...
        ---
        # 描述文本
        """
        content = md_path.read_text(encoding="utf-8")
        
        # 提取 frontmatter（YAML 块）
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            logger.warning(f"No frontmatter in {md_path}")
            return None
        
        frontmatter_str = match.group(1)
        metadata_dict = self._parse_yaml_frontmatter(frontmatter_str)
        
        if not metadata_dict:
            return None
        
        try:
            metadata = SkillMetadata.from_dict(metadata_dict, skill_dir=skill_dir)
            logger.info(f"加载 skill: {metadata.name}")
            return metadata
        except Exception as e:
            logger.error(f"解析 SKILL.md 失败 {md_path}: {e}")
            return None
    
    @staticmethod
    def _parse_yaml_frontmatter(yaml_str: str) -> Dict[str, Any]:
        """
        简易 YAML 解析器（仅支持基础字段）
        
        实际项目可用 PyYAML，这里为了教学简化实现
        """
        result = {}
        
        # 分行处理
        for line in yaml_str.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                
                # 基础类型转换
                if value.lower() == "true":
                    result[key] = True
                elif value.lower() == "false":
                    result[key] = False
                elif value.startswith("[") and value.endswith("]"):
                    # 简单列表解析
                    result[key] = [
                        v.strip().strip('"').strip("'")
                        for v in value[1:-1].split(",")
                        if v.strip()
                    ]
                elif value.startswith("{") and value.endswith("}"):
                    # 简单字典解析
                    try:
                        result[key] = json.loads(value)
                    except:
                        result[key] = value
                else:
                    # 去掉引号
                    result[key] = value.strip('"').strip("'")
        
        return result
    
    def load_skill_impl(self, metadata: SkillMetadata):
        """
        动态加载 skill 的 Python 实现
        
        约定：skill_dir/skill.py 中的 SkillImpl 类
        """
        impl_path = metadata.skill_dir / "skill.py"
        
        if not impl_path.exists():
            raise FileNotFoundError(f"Skill implementation not found: {impl_path}")
        
        import importlib.util
        
        spec = importlib.util.spec_from_file_location(
            f"skill_{metadata.name}", impl_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        if not hasattr(module, "SkillImpl"):
            raise AttributeError(f"SkillImpl class not found in {impl_path}")
        
        return module.SkillImpl
