
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
MEMORY_FILE_PATH = BASE_DIR / "data" / "memory.json"

# ---------- 新增：追加模式（O(1) 写入） ----------
def append_memory(entry: dict) -> bool:
    """
    将单条对话记录追加到文件末尾。
    """
    try:
        MEMORY_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MEMORY_FILE_PATH, 'a', encoding='utf-8') as f:
            # 每行一个完整的 JSON 对象，加换行符
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return True
    except Exception as e:
        print(f"[Memory] 追加失败: {e}")
        return False

# ---------- 读取全部 ----------
def readMemory() -> list:
    """返回所有历史记录列表"""
    if not MEMORY_FILE_PATH.exists():
        return []
    
    entries = []
    with open(MEMORY_FILE_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    # 忽略单行损坏，保证整体可用
                    continue
    return entries

# ---------- 全量覆盖写入（用于重置或压缩） ----------
def writeMemory(memory: list) -> bool:
    """全量覆盖写入"""
    try:
        MEMORY_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MEMORY_FILE_PATH, 'w', encoding='utf-8') as f:
            for entry in memory:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return True
    except Exception as e:
        print(f"[Memory] 全量写入失败: {e}")
        return False

# ---------- 可选：滑动窗口压缩（防止文件无限膨胀） ----------
MAX_HISTORY_LINES = 300  # 最多保留 300 条记录

def compress_memory_if_needed():
    """如果记录超过上限，保留最近的 N 条"""
    all_data = readMemory()
    if len(all_data) > MAX_HISTORY_LINES:
        trimmed = all_data[-MAX_HISTORY_LINES:]
        writeMemory(trimmed)
        print(f"[Memory] 已压缩至 {MAX_HISTORY_LINES} 条")
        return True
    return False
