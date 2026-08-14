"""
Skill 调用记录器 — Layer S4：将 Skill 调用结果写回四层记忆

教学重点：
  1. **复用原项目的记忆写入路径**：USER.md（用户偏好）/ MEMORY.md（事实）/ FAISS（语义检索）
  2. **Skill 特有分类**：每条调用记录带 `category=skill_call`、tag=`skill:<name>`
  3. **append-only 增量**：避免覆盖已有记忆，仅追加
  4. **降级写入**：如果 LLM 提取失败，仍能保留"原始调用"作为 fact 类条目

使用方式：
  recorder = SkillRecorder()
  recorder.record_call(skill_name="translate", params={"text": "..."},
                       result=result, user_query="翻译这段话")
"""

import os
import re
import json
import logging
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from src.memory_loader import MemoryLoader
from src.vector_store import VectorStore
from src.fts_store import FTSStore

logger = logging.getLogger(__name__)

MEMORY_DIR = Path(__file__).parent.parent / "memory"


@dataclass
class RecordedCall:
    """一条 Skill 调用的完整记录"""
    skill_name: str
    user_query: str
    params: dict
    output_text: str
    success: bool
    duration_ms: float
    timestamp: str
    category: str = "skill_call"          # 长期记忆 category
    title: str = ""
    importance: str = "medium"            # high / medium / low → 影响是否进 FAISS


class SkillRecorder:
    """将 Skill 调用写入 USER.md / MEMORY.md / 每日日志 / FAISS / FTS5"""

    def __init__(self, memory_dir: Path = MEMORY_DIR):
        self.memory_dir = memory_dir
        self.loader = MemoryLoader(memory_dir)
        self.vs = VectorStore()
        self.fts = FTSStore()
        self.user_md_path = self.loader.get_user_md_path()
        self.memory_md_path = self.loader.get_memory_md_path()

    def record_call(
        self,
        skill_name: str,
        params: dict,
        result_text: str,
        user_query: str,
        success: bool,
        duration_ms: float,
        category: str = "skill_call",
        title: str = "",
    ) -> RecordedCall:
        """记录一次 Skill 调用"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        ts_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

        call = RecordedCall(
            skill_name=skill_name,
            user_query=user_query,
            params=params,
            output_text=result_text[:500] if result_text else "",  # 截短，避免 MEMORY.md 膨胀
            success=success,
            duration_ms=duration_ms,
            timestamp=now,
            category=category,
            title=title or f"调用 skill: {skill_name}",
            importance="medium",
        )

        # 1. 追加到 MEMORY.md（自动写入 FAISS + FTS5）
        try:
            entry_id = f"skill_{skill_name}_{ts_id}"
            entry = {
                "id": entry_id,
                "category": call.category,
                "title": call.title,
                "content": (
                    f"用户请求：{user_query[:200]}\n"
                    f"调用 skill：{skill_name}\n"
                    f"参数：{json.dumps(params, ensure_ascii=False)[:200]}\n"
                    f"结果：{call.output_text[:300]}"
                ),
                "date": now,
            }
            self._append_to_memory_md([entry])
            self._append_to_daily_log(entry)

            # 写入向量索引 + FTS（让用户后续问"我之前用过哪些翻译 skill"也能召回）
            self.vs.add_entries([entry])
            if self.fts.available:
                self.fts.add_entries([entry])

            logger.info(f"Skill '{skill_name}' 调用已写入记忆（id={entry_id}）")
        except Exception as e:
            logger.error(f"写入 Skill 记忆失败：{e}")

        # 2. 更新 USER.md 中的"用户使用过的 skills"列表
        try:
            self._update_user_skills(skill_name)
        except Exception as e:
            logger.warning(f"更新 USER.md skills 列表失败：{e}")

        return call

    # ── 内部 ──────────────────────────────────────────────────────────────────

    def _append_to_memory_md(self, entries: list[dict]):
        """复用 MemoryFlusher 的格式（保持向后兼容）"""
        content = self.memory_md_path.read_text(encoding="utf-8")
        end_marker = "<!-- MEMORY_ENTRIES_END -->"
        blocks = []
        for entry in entries:
            block = (
                f"### [{entry.get('category', 'skill_call')}] {entry.get('title', '未命名')}\n"
                f"记录时间：{entry.get('date', '')}\n\n"
                f"{entry.get('content', '')}"
            )
            blocks.append(block)
        insertion = "\n\n".join(blocks) + "\n\n"
        updated = content.replace(end_marker, insertion + end_marker)
        self.memory_md_path.write_text(updated, encoding="utf-8")

    def _append_to_daily_log(self, entry: dict):
        """追加到 memory/YYYY-MM-DD.md（短期记忆）"""
        log_path = self.memory_dir / f"{date.today().isoformat()}.md"
        now = datetime.now().strftime("%H:%M")
        lines = [
            f"\n## {now} skill: {entry.get('title', '调用')}\n",
            f"- {entry.get('content', '').replace(chr(10), ' ')}",
            "",
        ]
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _update_user_skills(self, skill_name: str):
        """在 USER.md 中维护"用户偏好/用过的 skills"小节"""
        if not self.user_md_path.exists():
            return
        content = self.user_md_path.read_text(encoding="utf-8")
        marker = "## 用过的 Skills"
        if marker not in content:
            content += f"\n\n{marker}\n（暂无）\n"
        # 提取 marker 下方内容
        idx = content.find(marker)
        section = content[idx:]
        next_section_idx = re.search(r"\n## ", section[len(marker):])
        end = idx + len(marker) + (next_section_idx.start() if next_section_idx else len(section))
        section_body = content[idx + len(marker):end].strip()

        # 简化：用行级 dedupe
        lines = [l.strip() for l in section_body.splitlines() if l.strip() and l.strip() != "（暂无）"]
        new_line = f"- {skill_name}（{date.today().isoformat()}）"
        if new_line not in lines:
            lines.append(new_line)
        if not lines:
            lines = ["（暂无）"]

        new_section = f"{marker}\n" + "\n".join(lines) + "\n"
        new_content = content[:idx] + new_section + content[end:].lstrip("\n")
        self.user_md_path.write_text(new_content, encoding="utf-8")