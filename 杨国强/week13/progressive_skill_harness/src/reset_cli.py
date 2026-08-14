"""
CLI 重置工具 — 替代直接调 /reset HTTP 端点的离线版本

使用方式：
  python src/reset_cli.py factory      # 回到出厂初始态
  python src/reset_cli.py backup       # 创建当前状态快照
  python src/reset_cli.py restore      # 恢复最近一次快照
"""

import os
import sys
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
MEMORY_DIR = ROOT / "memory"
BACKUP_DIR = ROOT / "backups"
INDEX_DIR = ROOT / "data" / "vector_index"
DB_PATH = ROOT / "outputs" / "sessions" / "memory.db"

INITIAL_USER_MD = """\
# USER.md — 用户偏好与已知信息

> 本文件由 Memory Flush 与 SkillRecorder 自动维护，也可手动编辑。
> 最后更新：（尚未初始化）

## 基本信息
- 姓名：（尚未告知）
- 所在地：（尚未告知）
- 职业：（尚未告知）

## 偏好
（暂无记录，对话后由 Memory Flush 自动填充）

## 技术背景
（暂无记录）

## 沟通偏好
（暂无记录）

## 其他已知信息
（暂无记录）

## 用过的 Skills
（暂无）
"""

INITIAL_MEMORY_MD = """\
# MEMORY.md — 跨会话持久记忆

> 本文件由 Memory Flush 与 SkillRecorder 自动维护。
> 每条记忆格式：`### [类别] 标题` + 记录时间 + 内容
> 类别：preference（偏好）| fact（事实）| event（事件）| decision（决策）| skill_call（技能调用）

<!-- MEMORY_ENTRIES_START -->
<!-- MEMORY_ENTRIES_END -->
"""


def cmd_factory():
    """回到出厂初始态"""
    # 1. 备份 SOUL.md / AGENTS.md 到 backups/initial/memory/
    initial_mem_dir = BACKUP_DIR / "initial" / "memory"
    initial_mem_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("SOUL.md", "AGENTS.md"):
        src = MEMORY_DIR / fname
        if src.exists():
            shutil.copy2(src, initial_mem_dir / fname)

    # 2. 重置 USER.md / MEMORY.md
    (MEMORY_DIR / "USER.md").write_text(INITIAL_USER_MD, encoding="utf-8")
    (MEMORY_DIR / "MEMORY.md").write_text(INITIAL_MEMORY_MD, encoding="utf-8")
    print("  ✓ memory/USER.md → 已重置")
    print("  ✓ memory/MEMORY.md → 已重置")

    # 3. 清空 FAISS
    if INDEX_DIR.exists():
        for f in ("memory.faiss", "memory_meta.pkl"):
            p = INDEX_DIR / f
            if p.exists():
                p.unlink()
        print("  ✓ data/vector_index/ → FAISS 已清空")

    # 4. 清空 SQLite
    if DB_PATH.exists():
        try:
            DB_PATH.unlink()
            print("  ✓ outputs/sessions/memory.db → 已删除")
        except PermissionError:
            conn = sqlite3.connect(DB_PATH)
            conn.executescript("DELETE FROM messages; DELETE FROM sessions;")
            try:
                conn.execute("DELETE FROM memory_fts")
            except sqlite3.OperationalError:
                pass
            conn.commit()
            conn.close()
            print("  ✓ outputs/sessions/memory.db → 表已清空（文件被占用）")

    print("\n出厂初始态恢复完成。")


def cmd_backup():
    name = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap = BACKUP_DIR / name
    snap.mkdir(parents=True, exist_ok=True)
    if MEMORY_DIR.exists():
        shutil.copytree(MEMORY_DIR, snap / "memory", dirs_exist_ok=True)
    if INDEX_DIR.exists():
        shutil.copytree(INDEX_DIR, snap / "vector_index", dirs_exist_ok=True)
    if DB_PATH.exists():
        try:
            shutil.copy2(DB_PATH, snap / "memory.db")
        except PermissionError:
            print(f"  ⚠ SQLite 被占用，跳过（{DB_PATH}）")
    print(f"  ✓ 快照已保存：backups/{name}/")


def cmd_restore(name: str | None = None):
    if not BACKUP_DIR.exists():
        print("  无快照目录")
        return
    snaps = sorted([d.name for d in BACKUP_DIR.iterdir() if d.is_dir() and d.name != "initial"], reverse=True)
    if not snaps:
        print("  无快照")
        return
    if name is None:
        name = snaps[0]
        print(f"  使用最近快照：{name}")
    snap = BACKUP_DIR / name
    if (snap / "memory").exists():
        shutil.copytree(snap / "memory", MEMORY_DIR, dirs_exist_ok=True)
        print(f"  ✓ memory/ 已从 {name} 恢复")
    if (snap / "vector_index").exists():
        shutil.copytree(snap / "vector_index", INDEX_DIR, dirs_exist_ok=True)
        print(f"  ✓ data/vector_index/ 已从 {name} 恢复")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "factory":
        cmd_factory()
    elif cmd == "backup":
        cmd_backup()
    elif cmd == "restore":
        name = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_restore(name)
    else:
        print(f"未知命令：{cmd}")


if __name__ == "__main__":
    main()