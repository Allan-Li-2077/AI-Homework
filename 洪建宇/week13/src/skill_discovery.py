"""skill_discovery - 自动扫描 skills/ 目录获取元信息。

渐进式加载的关键点：
    本模块只通过 AST 解析读取每个 skill 文件顶层的 SKILL_META 字典，
    **不会** import skill 模块本身，因此不会触发 Pillow / moviepy 等重依赖。
    这样 list/info 命令可以瞬间完成，内存占用极低。
"""
import ast
import os
from typing import Any, Dict


def _extract_skill_meta(file_path: str) -> Dict[str, Any]:
    """用 AST 从源文件中安全提取 SKILL_META 字典。

    使用 ast.literal_eval 求值，只支持字面量（dict/list/str/int/float/bool/None），
    因此 SKILL_META 内不能出现函数调用或变量引用——这是 skill 编写约定。
    若文件中不存在 SKILL_META，返回空 dict。
    """
    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=file_path)

    # 在模块顶层查找形如 `SKILL_META = {...}` 或 `SKILL_META: dict = {...}` 的赋值。
    # 前者是 ast.Assign，后者是 ast.AnnAssign（带类型注解），均需兼容。
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "SKILL_META":
                try:
                    return ast.literal_eval(value)
                except (ValueError, SyntaxError) as e:
                    raise ValueError(f"{file_path} 中的 SKILL_META 必须是纯字面量: {e}")
    return {}


def discover_skills(skills_dir: str) -> Dict[str, Dict[str, Any]]:
    """扫描 skills 目录，返回 {skill_name: meta_dict}。

    - 跳过以 _ 开头的文件（如 __init__.py）
    - 只处理 .py 文件
    - 解析失败的单个文件会被跳过并打印警告，不影响其他 skill
    每条 meta 会额外注入 `file_path` 字段，便于后续加载定位。
    """
    skills: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(skills_dir):
        return skills

    for filename in sorted(os.listdir(skills_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        file_path = os.path.join(skills_dir, filename)
        try:
            meta = _extract_skill_meta(file_path)
        except Exception as e:
            print(f"[discovery] 跳过 {filename}: {e}")
            continue
        if not meta or "name" not in meta:
            continue
        # 注入来源路径，方便 harness 按需 import
        meta["file_path"] = file_path
        skills[meta["name"]] = meta

    return skills
