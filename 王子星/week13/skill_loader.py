"""
三层加载策略：
  L1 发现（scan_skills）：仅读取每个 SKILL.md 的 YAML frontmatter，
     提取 name/description/version，不加载正文，token 开销极低。
  L2 匹配（get_skill_index_prompt）：将摘要清单嵌入 system prompt，
     由 LLM 根据用户输入判断激活哪个 skill。
  L3 注入（load_full_skill / load_reference）：仅被激活的 skill
     按需加载完整正文 + references，注入后替换 system prompt，用完即释。
"""

import re
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SkillInfo:
    """一个 skill 的元数据（L1）与延迟加载内容（L3）"""
    name: str                                        # SKILL.md frontmatter 中的 name
    description: str                                 # 触发场景描述
    version: str                                     # 语义化版本号
    base_dir: Path                                   # skill 根目录
    has_scripts: bool = False                        # 是否含 scripts/
    has_references: bool = False                     # 是否含 references/
    _full_content: str | None = field(default=None, repr=False)   # 延迟加载的完整正文


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    解析 SKILL.md 开头的 YAML frontmatter（--- 包裹块）。
    纯标准库实现，仅处理 name/description/version 三个字段，
    description 支持 >- 折叠块语法。

    Returns:
        (metadata_dict, body_without_frontmatter)
    """
    # 匹配开头 --- ... --- 块
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', text, re.DOTALL)
    if not m:
        return {}, text

    fm_block, body = m.group(1), m.group(2)
    meta: dict = {}

    # 处理 >- 多行折叠块（description 常用写法）
    # 思路：找到 "key: >-" 后，把紧随其后缩进的行合并为一个字符串
    current_key: str | None = None
    folded_lines: list[str] = []

    def _flush():
        nonlocal current_key, folded_lines
        if current_key:
            meta[current_key] = " ".join(folded_lines).strip()
            current_key = None
            folded_lines = []

    for line in fm_block.splitlines():
        # 折叠续行：以 2+ 空格开头
        if current_key and re.match(r'^  +\S', line):
            folded_lines.append(line.strip())
            continue

        _flush()

        if line.startswith("name:"):
            meta["name"] = line.split(":", 1)[1].strip().strip('"\'')
        elif line.startswith("description:"):
            val = line.split(":", 1)[1].strip()
            if val in (">-", ">|", "|"):
                # 多行折叠，等待后续缩进行
                current_key = "description"
                folded_lines = []
            else:
                meta["description"] = val.strip('"\'')
        elif line.startswith("version:"):
            meta["version"] = line.split(":", 1)[1].strip().strip('"\'')

    _flush()
    return meta, body


def scan_skills(skills_dir: Path) -> list[SkillInfo]:
    """
    扫描 skills_dir 下所有子目录，找到含 SKILL.md 的目录并解析元数据。
    """
    skills: list[SkillInfo] = []

    if not skills_dir.exists():
        logger.warning(f"skills 目录不存在: {skills_dir}")
        return skills

    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            continue

        try:
            text = skill_md.read_text(encoding="utf-8")
            meta, _ = _parse_frontmatter(text)
            if not meta.get("name"):
                logger.warning(f"跳过 {child.name}：SKILL.md 缺少 name 字段")
                continue

            skills.append(SkillInfo(
                name=meta["name"],
                description=meta.get("description", "（无描述）"),
                version=meta.get("version", "1.0"),
                base_dir=child,
                has_scripts=(child / "scripts").is_dir(),
                has_references=(child / "references").is_dir(),
            ))
            logger.info(f"发现 skill: {meta['name']} @ {child}")
        except Exception as e:
            logger.warning(f"解析 {child.name}/SKILL.md 失败: {e}")

    return skills


def get_skill_index_prompt(skills: list[SkillInfo]) -> str:
    """
    将所有 skill 的 name + description 拼成一段"技能清单"文本，
    """
    if not skills:
        return "当前无可用技能。"

    lines = ["以下是当前可用的技能列表：", ""]
    for i, s in enumerate(skills, 1):
        lines.append(f"{i}. **{s.name}**（v{s.version}）：{s.description}")
    lines.append("")
    lines.append(
        "当用户的请求匹配某个技能时，你必须先输出一行激活标记，格式如下：\n"
        "  skill_activated:<技能名称>\n"
        "然后从下一行开始按该技能的指令执行。若无匹配技能则正常回答。"
    )
    return "\n".join(lines)


def load_full_skill(skill: SkillInfo) -> str:
    """
    加载完整 SKILL.md 正文，缓存到 _full_content。
    """
    if skill._full_content is not None:
        return skill._full_content

    skill_md = skill.base_dir / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    _, body = _parse_frontmatter(text)

    # 将 {baseDir} 占位符替换为实际路径，让 LLM 知道脚本在哪里
    body = body.replace("{baseDir}", str(skill.base_dir).replace("\\", "/"))

    skill._full_content = body
    return body


def load_reference(skill: SkillInfo, filename: str) -> str | None:
    """按需加载 references/ 下的某个参考文档（如 architecture.md）"""
    ref_path = skill.base_dir / "references" / filename
    if ref_path.exists():
        return ref_path.read_text(encoding="utf-8")
    logger.warning(f"参考文档不存在: {ref_path}")
    return None


def list_references(skill: SkillInfo) -> list[str]:
    """列出 skill 下 references/ 目录中所有可用文件名"""
    ref_dir = skill.base_dir / "references"
    if not ref_dir.exists():
        return []
    return sorted(f.name for f in ref_dir.iterdir() if f.is_file())


def build_skill_system_prompt(skill: SkillInfo) -> str:
    """
    将完整 SKILL.md 正文包装为增强版 system prompt。
    注入实际目录路径，确保 LLM 知道脚本和数据的真实位置。
    如有 references 目录，在末尾附加文件清单，供 LLM 按需索取。
    """
    full = load_full_skill(skill)
    skill_base = str(skill.base_dir).replace("\\", "/")

    prompt = (
        f"## 已激活技能：{skill.name}\n\n"
        f"**重要：技能实际目录为 `{skill_base}`**\n"
        f"所有脚本路径和数据路径必须基于此目录，不要使用文档中的示例路径。\n\n"
        f"**运行环境：Windows 系统，使用 cmd 解释器。**\n"
        f"需要执行操作时，请使用 ```python 代码块（而非 bash），因为 Python 跨平台可靠。\n"
        f"在 Python 代码中用 os.makedirs() 创建目录、用 json.dump() 写文件、用 subprocess.run() 调用脚本。\n\n"
        f"{full}\n\n"
        f"---\n"
        f"请严格按照上述技能指令执行。"
        f"需要运行脚本时，将完整 Python 代码放在 ```python 代码块中，系统会自动执行。"
        f"绝对不要询问用户是否允许执行——直接执行。"
    )

    refs = list_references(skill)
    if refs:
        ref_list = "\n".join(f"  - {r}" for r in refs)
        prompt += (
            f"\n\n本技能包含以下参考文档，需要时请告知读取哪份：\n{ref_list}"
        )

    return prompt
