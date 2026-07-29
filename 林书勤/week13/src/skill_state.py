"""
Stage 4: State Management & Persistence (状态管理与持久化)

职责：
  1. 记录 skill 执行历史
  2. 缓存执行结果
  3. 保存执行快照（YAML）
  4. 支持结果查询与复用

设计理念（与 week13 对应）：
  - 类比 Layer 2 (SQLite)：execution_history 表
  - 类比 Layer 3 (MEMORY.md)：执行快照 YAML 文件
  - 类比 Compaction：清理旧记录，保留最近 N 条
"""

import sqlite3
import json
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRecord:
    """执行记录（对应数据库行）"""
    id: int = None
    timestamp: str = None
    skill_name: str = ""
    status: str = ""  # "success", "failed", "skipped"
    params: Dict[str, Any] = None
    result: Any = None
    error: str = None
    duration_ms: int = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "skill_name": self.skill_name,
            "status": self.status,
            "params": self.params or {},
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


class SkillState:
    """
    状态管理器
    
    管理：
      1. SQLite 执行历史（长期记忆）
      2. 内存缓存（工作记忆）
      3. YAML 快照（检查点）
    """
    
    def __init__(self, state_dir: Path = None):
        self.state_dir = state_dir or Path(__file__).parent.parent / "state"
        self.state_dir.mkdir(exist_ok=True)
        
        # 创建必要的子目录
        self.cache_dir = self.state_dir / "cache"
        self.cache_dir.mkdir(exist_ok=True)
        
        self.snapshots_dir = self.state_dir / "snapshots"
        self.snapshots_dir.mkdir(exist_ok=True)
        
        # 初始化数据库
        self.db_path = self.state_dir / "skills.db"
        self._init_database()
        
        # 内存缓存
        self._memory_cache: Dict[str, Any] = {}
    
    def _init_database(self):
        """初始化 SQLite 数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建表（如果不存在）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS execution_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                status TEXT NOT NULL,
                params TEXT,
                result TEXT,
                error TEXT,
                duration_ms INTEGER
            )
        """)
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_skill_name
            ON execution_history(skill_name)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON execution_history(timestamp DESC)
        """)
        
        conn.commit()
        conn.close()
    
    def save_record(self, record: ExecutionRecord) -> int:
        """
        保存执行记录到数据库
        
        Returns:
            记录 ID
        """
        record.timestamp = record.timestamp or datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO execution_history
            (timestamp, skill_name, status, params, result, error, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            record.timestamp,
            record.skill_name,
            record.status,
            json.dumps(record.params or {}, ensure_ascii=False),
            json.dumps(result_to_serializable(record.result), ensure_ascii=False),
            record.error,
            record.duration_ms,
        ))
        
        record_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"保存记录: {record.skill_name} (ID: {record_id})")
        return record_id
    
    def get_record(self, record_id: int) -> Optional[ExecutionRecord]:
        """获取单条记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM execution_history WHERE id = ?",
            (record_id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return self._row_to_record(row)
    
    def get_latest_records(
        self,
        skill_name: str = None,
        limit: int = 10,
    ) -> List[ExecutionRecord]:
        """
        获取最近的记录
        
        Args:
            skill_name: 过滤特定 skill（None 表示所有）
            limit: 返回数量限制
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if skill_name:
            cursor.execute("""
                SELECT * FROM execution_history
                WHERE skill_name = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (skill_name, limit))
        else:
            cursor.execute("""
                SELECT * FROM execution_history
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_record(row) for row in rows]
    
    def get_success_result(self, skill_name: str) -> Optional[Any]:
        """
        获取最近一次成功执行的结果
        （用于依赖注入和缓存复用）
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT result FROM execution_history
            WHERE skill_name = ? AND status = 'success'
            ORDER BY timestamp DESC
            LIMIT 1
        """, (skill_name,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0]:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return None
        
        return None
    
    def clear_old_records(self, skill_name: str = None, keep_count: int = 50):
        """
        清理旧记录（类比 Compaction）
        
        保留最近 keep_count 条记录，其余删除
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if skill_name:
            # 删除特定 skill 的旧记录
            cursor.execute("""
                DELETE FROM execution_history
                WHERE skill_name = ?
                AND id NOT IN (
                    SELECT id FROM execution_history
                    WHERE skill_name = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                )
            """, (skill_name, skill_name, keep_count))
        else:
            # 删除所有旧记录
            cursor.execute("""
                DELETE FROM execution_history
                WHERE id NOT IN (
                    SELECT id FROM execution_history
                    ORDER BY timestamp DESC
                    LIMIT ?
                )
            """, (keep_count,))
        
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        logger.info(f"清理 {deleted} 条旧记录")
    
    def save_snapshot(
        self,
        snapshot_name: str,
        data: Dict[str, Any],
    ):
        """
        保存执行快照（YAML）
        
        用于检查点、调试等
        """
        snapshot_path = self.snapshots_dir / f"{snapshot_name}.yaml"
        
        with open(snapshot_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        
        logger.info(f"保存快照: {snapshot_name}")
    
    def load_snapshot(self, snapshot_name: str) -> Optional[Dict[str, Any]]:
        """加载执行快照"""
        snapshot_path = self.snapshots_dir / f"{snapshot_name}.yaml"
        
        if not snapshot_path.exists():
            logger.warning(f"快照不存在: {snapshot_name}")
            return None
        
        with open(snapshot_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        logger.info(f"加载快照: {snapshot_name}")
        return data
    
    def list_snapshots(self) -> List[str]:
        """列出所有快照"""
        snapshots = [
            p.stem for p in self.snapshots_dir.glob("*.yaml")
        ]
        return sorted(snapshots, reverse=True)
    
    # ── 内存缓存（工作记忆）──────────────────────────────────────────
    
    def cache_result(self, key: str, value: Any):
        """缓存结果（内存）"""
        self._memory_cache[key] = value
    
    def get_cached_result(self, key: str) -> Optional[Any]:
        """获取缓存"""
        return self._memory_cache.get(key)
    
    def clear_cache(self):
        """清空缓存"""
        self._memory_cache.clear()
    
    # ── 工具方法──────────────────────────────────────────────────────
    
    @staticmethod
    def _row_to_record(row: tuple) -> ExecutionRecord:
        """将数据库行转换为 ExecutionRecord"""
        return ExecutionRecord(
            id=row[0],
            timestamp=row[1],
            skill_name=row[2],
            status=row[3],
            params=json.loads(row[4]) if row[4] else None,
            result=json.loads(row[5]) if row[5] else None,
            error=row[6],
            duration_ms=row[7],
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取执行统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 总记录数
        cursor.execute("SELECT COUNT(*) FROM execution_history")
        total = cursor.fetchone()[0]
        
        # 按 status 统计
        cursor.execute("""
            SELECT status, COUNT(*) FROM execution_history
            GROUP BY status
        """)
        status_counts = dict(cursor.fetchall())
        
        # 按 skill 统计
        cursor.execute("""
            SELECT skill_name, COUNT(*) FROM execution_history
            GROUP BY skill_name
            ORDER BY COUNT(*) DESC
        """)
        skill_counts = dict(cursor.fetchall())
        
        conn.close()
        
        return {
            "total_records": total,
            "status_counts": status_counts,
            "skill_counts": skill_counts,
            "cache_size": len(self._memory_cache),
            "snapshots_count": len(self.list_snapshots()),
        }


def result_to_serializable(obj: Any) -> Any:
    """将任意对象转换为可 JSON 序列化的形式"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [result_to_serializable(x) for x in obj]
    elif isinstance(obj, dict):
        return {k: result_to_serializable(v) for k, v in obj.items()}
    else:
        return str(obj)
