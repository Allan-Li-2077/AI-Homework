"""
技能加载器 — 从 skills/ 目录读取 SKILL.md，解析元数据与详细说明

设计要点：
  1. 支持两种格式：YAML Front Matter（--- 包裹）和简单键值对
  2. Skill dataclass 包含 name / brief / detail / folder_name / trigger_keywords
  3. trigger_keywords 从 description 中提取，用于 match_skill() 关键词匹配
  4. 渐进式披露：先加载简介，需要时再读取详细说明
"""

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import yaml

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
DIM = "\033[2m"

SKILLS_DIR = Path(__file__).parent.parent / "skills"


@dataclass
class Skill:
    """技能定义：名称、简介、详细说明、文件夹名、触发关键词"""
    name: str
    brief: str
    detail: str
    file_path: Path
    folder_name: str = ""
    trigger_keywords: List[str] = field(default_factory=list)


class SkillLoader:
    """技能管理器：加载、查询、匹配"""

    def __init__(self, skills_dir: Path = SKILLS_DIR):
        self.skills_dir = skills_dir
        self._skills: Optional[List[Skill]] = None

    # ── 加载 ──────────────────────────────────────────────────────────────

    def load_all_skills(self) -> List[Skill]:
        """加载所有技能（带缓存）。扫描 skills/ 下的子目录，每个含 SKILL.md。"""
        if self._skills is not None:
            return self._skills

        skills: List[Skill] = []
        if not self.skills_dir.exists():
            print(f"{YELLOW}[警告] skills 目录不存在: {self.skills_dir}{RESET}")
            return skills

        for item in self.skills_dir.iterdir():
            if not item.is_dir():
                continue
            if item.name.startswith('.') or item.name in ['__pycache__', 'references', 'scripts', 'data']:
                print(f"{DIM}[调试] 跳过辅助目录: {item.name}{RESET}")
                continue

            skill_md = item / "SKILL.md"
            if not skill_md.exists():
                skill_md = item / "skill.md"
            if not skill_md.exists():
                print(f"{DIM}[调试] 目录 {item.name} 中未找到 SKILL.md，跳过{RESET}")
                continue

            content = skill_md.read_text(encoding="utf-8").strip()
            parsed = self._parse_skill_content(content)
            if parsed is None:
                print(f"{YELLOW}[警告] 技能文件夹 {item.name} 中的 SKILL.md 缺少 name 定义，已跳过{RESET}")
                continue

            name, brief, detail = parsed
            keywords = self._extract_trigger_keywords(brief)
            skills.append(Skill(
                name=name,
                brief=brief or name,
                detail=detail,
                file_path=skill_md,
                folder_name=item.name,
                trigger_keywords=keywords,
            ))
            print(f"{GREEN}[调试] 成功加载技能: {name} (来自 {item.name}, 触发词 {len(keywords)} 个){RESET}")

        self._skills = skills
        print(f"{CYAN}[调试] 共加载 {len(skills)} 个技能{RESET}")
        return skills

    def _parse_skill_content(self, content: str) -> Optional[Tuple[str, str, str]]:
        """
        解析 SKILL.md 内容，返回 (name, brief, detail)。
        优先尝试 YAML Front Matter，失败则回退到简单键值对解析。
        """
        lines = content.splitlines()

        # 尝试 YAML Front Matter（以 --- 开头）
        if lines and lines[0].strip() == '---':
            end_index = None
            for i in range(1, len(lines)):
                if lines[i].strip() == '---':
                    end_index = i
                    break
            if end_index is not None:
                front_matter_text = '\n'.join(lines[1:end_index])
                detail = '\n'.join(lines[end_index + 1:]).strip()
                try:
                    meta = yaml.safe_load(front_matter_text)
                    if isinstance(meta, dict):
                        name = meta.get('name')
                        brief = meta.get('description') or meta.get('brief')
                        if name:
                            return str(name), str(brief or name), detail
                except yaml.YAMLError:
                    pass  # YAML 损坏，回退

        # 回退到简单键值对解析
        return self._parse_simple_format(content)

    def _parse_simple_format(self, content: str) -> Optional[Tuple[str, str, str]]:
        """处理无 Front Matter 的简单格式：name: xxx / description: xxx / 空行 / 详细内容"""
        lines = content.splitlines()
        name = None
        brief = None
        detail_lines: List[str] = []
        in_meta = True

        for line in lines:
            stripped = line.strip()
            if in_meta:
                if not stripped:
                    in_meta = False
                    continue
                if ':' in stripped:
                    key, val = stripped.split(':', 1)
                    key = key.strip().lower()
                    val = val.strip()
                    if key == 'name':
                        name = val
                    elif key in ('description', 'brief'):
                        brief = val
                else:
                    in_meta = False
                    detail_lines.append(line)
            else:
                detail_lines.append(line)

        detail = '\n'.join(detail_lines).strip()
        if name:
            return name, brief or name, detail
        return None

    def _extract_trigger_keywords(self, brief: str) -> List[str]:
        """
        从技能简介中提取触发关键词。
        策略：提取引号内的内容、中英文关键词、常见触发短语。
        """
        keywords: List[str] = []

        # 提取引号内的内容（如 "闪卡"、"flash card"）
        quoted = re.findall(r'[""「]([^""」]+)[""」]', brief)
        keywords.extend(quoted)

        # 常见触发词模式
        trigger_patterns = [
            r'闪卡', r'flash\s*card', r'单词卡',
            r'图表', r'图', r'diagram', r'flowchart', r'架构图', r'流程图',
            r'时序图', r'sequence', r'画', r'draw',
        ]
        for pattern in trigger_patterns:
            matches = re.findall(pattern, brief, re.IGNORECASE)
            keywords.extend(matches)

        # 去重并保留顺序
        seen = set()
        unique = []
        for kw in keywords:
            kw_lower = kw.lower().strip()
            if kw_lower and kw_lower not in seen:
                seen.add(kw_lower)
                unique.append(kw_lower)
        return unique

    # ── 查询 ──────────────────────────────────────────────────────────────

    def get_skill_detail(self, name: str) -> Optional[str]:
        """根据技能名获取详细说明"""
        for skill in self.load_all_skills():
            if skill.name == name:
                return skill.detail
        return None

    def get_skill_folder(self, name: str) -> str:
        """返回技能所在文件夹名，用于 {baseDir} 占位符替换"""
        for skill in self.load_all_skills():
            if skill.name == name:
                return skill.folder_name
        return name

    def get_skill(self, name: str) -> Optional[Skill]:
        """根据技能名获取完整 Skill 对象"""
        for skill in self.load_all_skills():
            if skill.name == name:
                return skill
        return None

    def match_skill(self, user_input: str) -> Optional[Skill]:
        """
        基于触发关键词匹配最合适的技能。
        返回匹配关键词最多的技能；无匹配返回 None。
        """
        input_lower = user_input.lower()
        best_skill: Optional[Skill] = None
        best_score = 0

        for skill in self.load_all_skills():
            score = 0
            for kw in skill.trigger_keywords:
                if kw in input_lower:
                    score += 1
            # 技能名本身也是关键词
            if skill.name.lower() in input_lower:
                score += 2
            if score > best_score:
                best_score = score
                best_skill = skill

        return best_skill

    # ── 格式化 ────────────────────────────────────────────────────────────

    def format_skills_brief(self) -> str:
        """格式化技能简介列表，供注入 LLM system prompt"""
        skills = self.load_all_skills()
        if not skills:
            return ""
        lines = [f"- {s.name}: {s.brief}" for s in skills]
        return "\n".join(lines)

    def print_skills_info(self, skills: Optional[List[Skill]] = None, show_details: bool = False) -> None:
        """以统一格式打印技能列表，用于调试和教学展示"""
        if skills is None:
            skills = self.load_all_skills()

        print(f"\n{CYAN}{'─' * 60}{RESET}")
        print(f"{CYAN}  Skills 加载情况（渐进式披露）{RESET}")
        print(f"{CYAN}{'─' * 60}{RESET}")

        if not skills:
            print(f"  {DIM}（无可用技能）{RESET}")
        else:
            print(f"  共加载 {len(skills)} 个技能：")
            for idx, s in enumerate(skills, 1):
                print(f"  {idx}. {GREEN}{s.name}{RESET}  {DIM}—— {s.brief[:60]}{RESET}")
                print(f"      文件夹：{s.folder_name}，详细说明：{len(s.detail)} 字符，触发词：{s.trigger_keywords}")
                if show_details:
                    preview = s.detail[:60].replace('\n', ' ')
                    if len(s.detail) > 60:
                        preview += "..."
                    print(f"      预览：{DIM}{preview}{RESET}")
        print(f"{CYAN}{'─' * 60}{RESET}\n")


if __name__ == "__main__":
    loader = SkillLoader()
    skills = loader.load_all_skills()
    loader.print_skills_info(skills, show_details=True)

    # 测试关键词匹配
    print(f"{MAGENTA}=== 关键词匹配测试 ==={RESET}")
    test_inputs = [
        "给我做一张 crazy 的闪卡",
        "画一个系统架构图",
        "帮我生成 resilient 的单词卡",
        "画个流程图",
    ]
    for inp in test_inputs:
        matched = loader.match_skill(inp)
        if matched:
            print(f"  '{inp}' → {GREEN}{matched.name}{RESET}")
        else:
            print(f"  '{inp}' → {DIM}无匹配{RESET}")