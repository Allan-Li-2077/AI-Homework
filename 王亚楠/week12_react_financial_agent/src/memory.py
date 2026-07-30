"""
记忆系统 — ReAct Financial Agent 持久化记忆

两层记忆：
  1. Conversation Memory — 按 session 组织的 Q&A 历史
  2. Fact Memory — 自动/手动提取的关键财务事实

存储：JSON 文件，零外部依赖

使用方式：
  from memory import MemoryStore
  store = MemoryStore()
  store.save_conversation(question, answer, steps, "manual", "default")
  ctx = store.build_context("新问题")
"""

import json
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 默认记忆目录（项目根目录下的 memory/）
DEFAULT_MEMORY_DIR = Path(__file__).parent.parent / "memory"


class MemoryStore:
    """持久化记忆存储，管理对话历史和事实知识"""

    def __init__(self, memory_dir: Optional[Path] = None):
        self.memory_dir = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR
        self.conv_dir = self.memory_dir / "conversations"
        self.facts_path = self.memory_dir / "facts.json"
        self._facts_cache: Optional[dict] = None
        self._ensure_dirs()

    def _ensure_dirs(self):
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.conv_dir.mkdir(parents=True, exist_ok=True)
        if not self.facts_path.exists():
            self.facts_path.write_text("{}", encoding="utf-8")

    # ═══════════════════════════════════════════════════════════════════
    # Conversation Memory — 对话历史
    # ═══════════════════════════════════════════════════════════════════

    def save_conversation(
        self,
        question: str,
        answer: str,
        steps: list,
        mode: str,
        session_id: str = "default",
    ) -> dict:
        """持久化一段对话到 session 文件"""
        conv_file = self.conv_dir / f"{session_id}.json"

        if conv_file.exists():
            data = json.loads(conv_file.read_text(encoding="utf-8"))
        else:
            data = {
                "session_id": session_id,
                "created_at": datetime.now().isoformat(),
                "turns": [],
            }

        action_steps = [s for s in steps if s.get("type") == "action"]
        turn = {
            "id": len(data["turns"]) + 1,
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "answer": answer[:500],
            "mode": mode,
            "steps_count": len(action_steps),
            "tools_used": [s.get("action") for s in action_steps],
        }
        data["turns"].append(turn)
        data["updated_at"] = datetime.now().isoformat()

        conv_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 自动从对话中提取事实
        self._extract_facts_from_turn(question, answer, steps)

        logger.info(f"对话已保存: session={session_id}, turn={turn['id']}")
        return turn

    def load_recent(self, n: int = 5, session_id: str = "default") -> list[dict]:
        """加载指定 session 最近 n 条对话"""
        conv_file = self.conv_dir / f"{session_id}.json"
        if not conv_file.exists():
            return []
        data = json.loads(conv_file.read_text(encoding="utf-8"))
        return data.get("turns", [])[-n:]

    def _extract_facts_from_turn(self, question: str, answer: str, steps: list):
        """从对话中自动提取关键事实

        匹配模式：
        - "XX 的股票代码为 XXXXXX"
        - company_lookup 工具的成功 Observation
        """
        # 从 Observation 中提取股票代码映射
        code_pattern = re.findall(
            r"(\S+)\s*的股票代码为\s*(\d{6})", answer
        )
        for name, code in code_pattern:
            self.add_fact(f"股票代码:{name}", code, source="auto-extract")

        # 从步骤中提取 company_lookup 结果
        for s in steps:
            if s.get("action") == "company_lookup":
                obs = str(s.get("observation", ""))
                m = re.search(r"(\S+)\s*的股票代码为\s*(\d{6})", obs)
                if m:
                    self.add_fact(
                        f"股票代码:{m.group(1)}", m.group(2), source="auto-extract"
                    )

    # ═══════════════════════════════════════════════════════════════════
    # Fact Memory — 事实知识库
    # ═══════════════════════════════════════════════════════════════════

    def _load_facts(self) -> dict:
        if self._facts_cache is None:
            try:
                self._facts_cache = json.loads(
                    self.facts_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, FileNotFoundError):
                self._facts_cache = {}
        return self._facts_cache

    def _save_facts(self, facts: dict):
        self._facts_cache = facts
        self.facts_path.write_text(
            json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add_fact(self, key: str, value: Any, source: str = "manual") -> dict:
        """存储一个事实。key 已存在时追加到历史值列表"""
        facts = self._load_facts()
        entry = {"value": value, "source": source, "timestamp": datetime.now().isoformat()}

        if key in facts:
            existing = facts[key]
            if isinstance(existing, dict) and "values" in existing:
                # 去重：值与最新一条相同时跳过
                if existing["values"] and existing["values"][-1].get("value") == value:
                    return entry
                existing["values"].append(entry)
            else:
                facts[key] = {"values": [{"value": existing, "source": "unknown", "timestamp": ""}, entry]}
        else:
            facts[key] = {"values": [entry]}

        self._save_facts(facts)
        logger.info(f"事实已存储: {key} = {value}")
        return entry

    def get_fact(self, key: str) -> Optional[Any]:
        """获取某个事实的最新值"""
        facts = self._load_facts()
        entry = facts.get(key)
        if entry and isinstance(entry, dict) and "values" in entry:
            return entry["values"][-1]["value"]
        return entry

    def search_facts(self, query: str) -> list[dict]:
        """关键词搜索事实库，返回匹配项"""
        facts = self._load_facts()
        results = []
        q = query.lower()
        for key, entry in facts.items():
            if not isinstance(entry, dict) or "values" not in entry:
                continue
            if q in key.lower():
                results.append({
                    "key": key,
                    "value": entry["values"][-1]["value"],
                    "source": entry["values"][-1].get("source", ""),
                    "timestamp": entry["values"][-1].get("timestamp", ""),
                })
            else:
                for v in entry["values"]:
                    if q in str(v.get("value", "")).lower():
                        results.append({
                            "key": key,
                            "value": v.get("value"),
                            "source": v.get("source", ""),
                            "timestamp": v.get("timestamp", ""),
                        })
                        break
        return results[:10]

    def all_facts(self) -> dict:
        """返回全部事实"""
        return self._load_facts()

    # ═══════════════════════════════════════════════════════════════════
    # Context Building — 构建注入 Prompt 的记忆上下文
    # ═══════════════════════════════════════════════════════════════════

    def build_context(
        self,
        question: str,
        session_id: str = "default",
        max_facts: int = 10,
        max_history: int = 3,
    ) -> str:
        """构建紧凑的记忆上下文文本，注入 System Prompt

        包含：
        1. 已记住的财务事实（优先匹配问题中的公司名）
        2. 近期对话历史摘要
        """
        parts = []

        # 1. 相关事实
        facts = self._load_facts()
        # 从问题中提取公司名关键词
        company_keywords = []
        for name in [
            "贵州茅台", "茅台", "五粮液", "宁德时代", "中国平安", "平安",
            "海康威视", "海康",
        ]:
            if name in question:
                company_keywords.append(name)

        relevant_facts = []
        for key, entry in facts.items():
            if not isinstance(entry, dict) or "values" not in entry:
                continue
            # 股票代码映射始终包含
            if key.startswith("股票代码:"):
                relevant_facts.append(f"- {key}: {entry['values'][-1]['value']}")
            # 匹配问题中涉及的公司
            elif any(kw in key for kw in company_keywords):
                relevant_facts.append(
                    f"- {key}: {entry['values'][-1]['value']}"
                )

        if relevant_facts:
            parts.append(
                "## 已记住的关键信息（可直接使用，无需重复查询）\n"
                + "\n".join(relevant_facts[:max_facts])
            )

        # 2. 近期对话历史
        recent = self.load_recent(n=max_history, session_id=session_id)
        if recent:
            hist_lines = ["## 近期对话历史"]
            for t in recent:
                hist_lines.append(f"- 问: {t['question']}")
                hist_lines.append(f"  答: {t['answer'][:200]}")
            parts.append("\n".join(hist_lines))

        return "\n\n".join(parts) if parts else ""

    # ═══════════════════════════════════════════════════════════════════
    # 管理接口
    # ═══════════════════════════════════════════════════════════════════

    def list_sessions(self) -> list[dict]:
        """列出所有会话"""
        sessions = []
        for f in sorted(self.conv_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", f.stem),
                    "turns": len(data.get("turns", [])),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions

    def get_session(self, session_id: str = "default") -> Optional[dict]:
        """获取单个会话详情"""
        conv_file = self.conv_dir / f"{session_id}.json"
        if not conv_file.exists():
            return None
        return json.loads(conv_file.read_text(encoding="utf-8"))

    def clear_session(self, session_id: str = "default"):
        """删除一个会话"""
        conv_file = self.conv_dir / f"{session_id}.json"
        if conv_file.exists():
            conv_file.unlink()
            logger.info(f"会话已清除: {session_id}")

    def clear_all(self):
        """清空全部记忆"""
        for f in self.conv_dir.glob("*.json"):
            f.unlink()
        self.facts_path.write_text("{}", encoding="utf-8")
        self._facts_cache = {}
        logger.info("全部记忆已清除")

    def get_stats(self) -> dict:
        """获取记忆统计"""
        sessions = self.list_sessions()
        facts = self._load_facts()
        total_turns = sum(s["turns"] for s in sessions)
        return {
            "sessions_count": len(sessions),
            "total_turns": total_turns,
            "facts_count": len(facts),
            "memory_dir": str(self.memory_dir),
        }
