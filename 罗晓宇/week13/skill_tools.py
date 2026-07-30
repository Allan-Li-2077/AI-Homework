
from pathlib import Path

# skills文件在.vscode目录下
skill_dir = Path(__file__).parent.parent / ".vscode" / "skills" / "flash-card"


def read_skill_frontmatter() -> dict:
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.exists():
        return {"error": f"{skill_path} 不存在。"}
    
    with open(skill_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    frontmatter = {}
    if lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if ":" in line:
                key, value = line.split(":", 1)
                frontmatter[key.strip()] = value.strip()
    
    return frontmatter

def read_skill_content() -> str:
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.exists():
        return f"{skill_path} 不存在。"
    
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    return content

def execute_skill_command(command: list | str) -> str:
    import subprocess

    # 执行简单命令，捕获输出
    result = subprocess.run(
        command,                      # 命令用列表传，避免 shell 注入
        capture_output=True,         # 捕获 stdout 和 stderr
        text=True,                   # 以字符串形式返回（而非 bytes）
        timeout=10                   # 超时 10 秒
    )

    return result.stdout or result.stderr or ""
