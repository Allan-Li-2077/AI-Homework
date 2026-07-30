import re
import json
import subprocess
from pathlib import Path

from skill_loader import SkillIndex
DIM = "\033[2m"
RESET = "\033[0m"
YELLOW = "\033[33m"

class SkillExecutor:
    def execute(self, llm_response: str, skill: SkillIndex):
        """从 LLM 回答中提取 JSON 数据块和 bash 命令，依次执行"""
        # 1. 提取 ```json 代码块 → 写入 skill.data 目录
        for m in re.finditer(r"```json\r?\n(.*?)```", llm_response, re.DOTALL):
            data = json.loads(m.group(1))
            word = data.get("word", "unknown")
            out = skill.skill_dir / "data" / f"{word}.json"
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  {DIM}[Skill] 数据已写入 {out}{RESET}")
        # 2. 提取 ```bash 代码块 → 执行
        for m in re.finditer(r"```bash\r?\n(.*?)```", llm_response, re.DOTALL):
            cmd = m.group(1).strip()
            print(f"  {DIM}[Skill] 执行: {cmd}{RESET}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True,cwd=skill.skill_dir.parent.parent)
            if result.stdout:
                print(f"  {DIM}{result.stdout.strip()}{RESET}")
            if result.returncode != 0:
                print(f"  {YELLOW}[Skill] 错误: {result.stderr.strip()}{RESET}")