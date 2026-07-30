"""
Skill 元数据解析与渐进式加载模块

负责：
1. 扫描目录发现所有 Skill
2. 解析 SKILL.md 的 YAML frontmatter（元数据）
3. 渐进式加载：只解析元数据，执行时才加载完整内容
"""

import re
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillMeta:
    """Skill 元数据（从 YAML frontmatter 解析）"""

    name: str
    description: str
    version: str = "1.0.0"
    triggers: list[str] = field(default_factory=list)
    script: str = ""
    script_type: str = "python"  # python / typescript / shell
    working_dir: Path = field(default_factory=Path)

    # 运行时状态
    _content_loaded: bool = field(default=False, repr=False)
    _full_content: str = field(default="", repr=False)


class SkillLoader:
    """
    Skill 渐进式加载器

    设计原则：
    - 发现阶段：只读取 SKILL.md 的 YAML frontmatter（轻量）
    - 执行阶段：按需读取完整内容和脚本（惰性加载）
    """

    SKILL_FILENAME = "SKILL.md"
    YAML_PATTERN = re.compile(
        r"^---\s*\n(.*?)\n---\s*\n(.*)$",
        re.DOTALL,
    )

    def __init__(self):
        self._skills: dict[str, SkillMeta] = {}
        self._discovered: bool = False

    def discover(self, skill_dirs: list[Path]) -> list[SkillMeta]:
        """
        扫描目录，发现所有 Skill（只解析元数据）

        Args:
            skill_dirs: Skill 目录列表

        Returns:
            发现的 Skill 元数据列表
        """
        self._skills.clear()
        found = []

        for directory in skill_dirs:
            if not directory.exists():
                logger.warning(f"Skill 目录不存在: {directory}")
                continue

            # 遍历目录下的所有子目录，寻找 SKILL.md
            for item in directory.iterdir():
                if not item.is_dir():
                    continue

                skill_md = item / self.SKILL_FILENAME
                if not skill_md.exists():
                    continue

                try:
                    meta = self._parse_frontmatter(skill_md)
                    meta.working_dir = item
                    self._skills[meta.name] = meta
                    found.append(meta)
                    logger.info(f"发现 Skill: {meta.name} (v{meta.version})")
                except Exception as e:
                    logger.error(f"解析 Skill 失败 [{skill_md}]: {e}")

        self._discovered = True
        logger.info(f"共发现 {len(found)} 个 Skill")
        return found

    def _parse_frontmatter(self, filepath: Path) -> SkillMeta:
        """
        解析 SKILL.md 的 YAML frontmatter

        Args:
            filepath: SKILL.md 文件路径

        Returns:
            SkillMeta 对象
        """
        content = filepath.read_text(encoding="utf-8")
        match = self.YAML_PATTERN.match(content)

        if not match:
            raise ValueError(f"无效的 SKILL.md 格式（缺少 YAML frontmatter）: {filepath}")

        yaml_text = match.group(1)
        body_text = match.group(2)

        # 简单 YAML 解析（只处理 key: value 格式）
        meta_dict = self._simple_yaml_parse(yaml_text)

        # 提取脚本信息（从 body 中查找 script 路径）
        script = self._extract_script_path(body_text, filepath.parent)

        # 解析 triggers（支持列表或逗号分隔字符串）
        triggers = meta_dict.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [t.strip() for t in triggers.split(",") if t.strip()]

        return SkillMeta(
            name=meta_dict.get("name", filepath.parent.name),
            description=meta_dict.get("description", ""),
            version=meta_dict.get("version", "1.0.0"),
            triggers=triggers,
            script=script,
            script_type=meta_dict.get("script_type", self._detect_script_type(script)),
            working_dir=filepath.parent,
        )

    def _simple_yaml_parse(self, yaml_text: str) -> dict:
        """
        简单 YAML 解析器（只处理 key: value 和 key: [list]）

        Args:
            yaml_text: YAML 文本

        Returns:
            解析后的字典
        """
        result = {}
        current_key = None
        current_list = []

        for line in yaml_text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # 列表项
            if stripped.startswith("- "):
                if current_key:
                    current_list.append(stripped[2:].strip().strip('"\''))
                continue

            # 结束列表
            if current_key and current_list:
                result[current_key] = current_list
                current_list = []
                current_key = None

            # key: value
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                key = key.strip()
                value = value.strip().strip('"\'')
                current_key = key
                result[key] = value

        # 处理末尾的列表
        if current_key and current_list:
            result[current_key] = current_list

        return result

    def _extract_script_path(self, body: str, skill_dir: Path) -> str:
        """
        从 SKILL.md 正文中提取脚本路径

        查找模式：
        - `script: path/to/script.py`
        - `脚本路径：path/to/script.py`
        - 代码块中的脚本路径
        """
        # 查找 script 字段
        patterns = [
            r"script[:：]\s*(.+?)(?:\n|$)",
            r"脚本路径[:：]\s*(.+?)(?:\n|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                script = match.group(1).strip()
                # 如果路径存在则返回
                script_path = skill_dir / script
                if script_path.exists():
                    return str(script_path)
                return script

        # 自动探测：查找 scripts/ 目录下的可执行文件
        scripts_dir = skill_dir / "scripts"
        if scripts_dir.exists():
            for ext in (".py", ".ts", ".sh"):
                candidates = list(scripts_dir.glob(f"*{ext}"))
                if candidates:
                    return str(candidates[0])

        return ""

    def _detect_script_type(self, script_path: str) -> str:
        """根据文件扩展名检测脚本类型"""
        if not script_path:
            return "python"
        ext = Path(script_path).suffix.lower()
        mapping = {
            ".py": "python",
            ".ts": "typescript",
            ".js": "javascript",
            ".sh": "shell",
            ".bash": "shell",
        }
        return mapping.get(ext, "python")

    def load_full(self, skill_name: str) -> Optional[SkillMeta]:
        """
        完整加载指定 Skill（惰性加载）

        Args:
            skill_name: Skill 名称

        Returns:
            完整加载的 SkillMeta，如果不存在则返回 None
        """
        meta = self._skills.get(skill_name)
        if not meta:
            return None

        if meta._content_loaded:
            return meta

        # 读取完整的 SKILL.md 内容
        skill_md = meta.working_dir / self.SKILL_FILENAME
        if skill_md.exists():
            meta._full_content = skill_md.read_text(encoding="utf-8")
            meta._content_loaded = True
            logger.debug(f"完整加载 Skill: {skill_name}")

        return meta

    def get_skill(self, name: str) -> Optional[SkillMeta]:
        """获取已发现的 Skill 元数据（不触发完整加载）"""
        return self._skills.get(name)

    def list_skills(self) -> list[SkillMeta]:
        """列出所有已发现的 Skill"""
        return list(self._skills.values())

    def reload(self, skill_dirs: list[Path]) -> list[SkillMeta]:
        """重新扫描加载所有 Skill"""
        self._discovered = False
        return self.discover(skill_dirs)
