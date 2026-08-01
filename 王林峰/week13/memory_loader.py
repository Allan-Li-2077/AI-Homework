"""
Layer 3 长期记忆：Markdown 文件加载与 System Prompt 组装
新增：渐进式分片懒加载、Harness 分步加载回调、记忆分页读取
教学重点：
  1. Markdown 作为"记忆配置语言"：SOUL / USER / MEMORY / AGENTS.md 各司其职
  2. System Prompt 的分层拼接：人格 → 用户画像 → 操作规范 → 近期记忆
  3. Token 意识：每层注入多少 token，如何控制总量
  4. 渐进式加载：分页读取记忆、懒加载分层内容，适配 Harness 分步执行
使用方式：
  from src.memory_loader import MemoryLoader
  loader = MemoryLoader()
  # 一次性全量加载（原有逻辑兼容）
  result = loader.build_system_prompt(recent_memory_limit=10)
  # 渐进式分片加载（Harness专用）
  async for layer_chunk in loader.iter_layers_progressive(chunk_size=3):
      print(layer_chunk)
"""
import re
from datetime import date, timedelta
from pathlib import Path
from dataclasses import dataclass, field
import asyncio
MEMORY_DIR = Path(__file__).parent.parent / "memory"
@dataclass
class MemoryLayer:
    name: str
    source_file: str
    content: str
    char_count: int = 0
    def __post_init__(self):
        self.char_count = len(self.content)
@dataclass
class SystemPromptResult:
    system_prompt: str
    layers: list[MemoryLayer]
    total_chars: int = 0
    def __post_init__(self):
        self.total_chars = sum(l.char_count for l in self.layers)
@dataclass
class LoadChunk:
    """Harness 渐进加载分片返回体"""
    layer_name: str
    partial_content: str
    finished: bool
    layer_meta: dict
class MemoryLoader:
    def __init__(self, memory_dir: Path = MEMORY_DIR):
        self.memory_dir = memory_dir
        # 缓存层，避免重复IO
        self._layer_cache = {}
        self._memory_entry_cache = None
    def _read_md(self, filename: str) -> str:
        path = self.memory_dir / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()
    # 新增：分页渐进提取记忆条目（Harness核心）
    def _extract_memory_entries_paginated(self, memory_md: str, offset: int, limit: int) -> tuple[list[str], int]:
        """分页读取MEMORY条目，返回分片条目+总条目数"""
        start = memory_md.find("<!-- MEMORY_ENTRIES_START -->")
        end = memory_md.find("<!-- MEMORY_ENTRIES_END -->")
        if start == -1 or end == -1:
            return [], 0
        body = memory_md[start + len("<!-- MEMORY_ENTRIES_START -->"):end].strip()
        if not body:
            return [], 0
        entries = re.split(r"(?=### \[)", body)
        entries = [e.strip() for e in entries if e.strip()]
        total = len(entries)
        slice_chunk = entries[offset:offset+limit]
        return slice_chunk, total
    def _extract_memory_entries(self, memory_md: str, limit: int) -> str:
        """原有一次性读取逻辑，保留兼容"""
        start = memory_md.find("<!-- MEMORY_ENTRIES_START -->")
        end = memory_md.find("<!-- MEMORY_ENTRIES_END -->")
        if start == -1 or end == -1:
            return ""
        body = memory_md[start + len("<!-- MEMORY_ENTRIES_START -->"):end].strip()
        if not body:
            return ""
        entries = re.split(r"(?=### \[)", body)
        entries = [e.strip() for e in entries if e.strip()]
        recent = entries[-limit:] if len(entries) > limit else entries
        return "\n\n".join(recent)
    def _read_recent_day_logs(self, days: int = 2) -> tuple[str, list[str]]:
        """短期记忆（近端日志）：读取最近 N 天的 memory/YYYY-MM-DD.md。"""
        today = date.today()
        parts, sources = [], []
        for i in range(days):
            d = today - timedelta(days=i)
            p = self.memory_dir / f"{d.isoformat()}.md"
            if p.exists():
                text = p.read_text(encoding="utf-8").strip()
                if text:
                    parts.append(f"### {d.isoformat()}\n{text}")
                    sources.append(p.name)
        return ("\n\n".join(parts)).strip(), sources
    # 新增：异步迭代分层渐进加载器（Harness调用）
    async def iter_layers_progressive(self, chunk_size: int = 5, layer_callback=None):
        """
        分层逐块迭代加载所有记忆层，用于渐进式Harness执行
        :param chunk_size: 记忆条目单页大小
        :param layer_callback: 每完成一层触发回调，用于Harness日志打点
        yield LoadChunk 分片对象
        """
        layer_order = [
            ("soul", "SOUL.md"),
            ("daily_log", None),
            ("user_profile", "USER.md"),
            ("agents_manual", "AGENTS.md"),
            ("long_term_memory", "MEMORY.md"),
        ]
        for layer_name, file_name in layer_order:
            if layer_name == "soul":
                content = self._read_md(file_name)
                yield LoadChunk(
                    layer_name="soul", partial_content=content, finished=True,
                    layer_meta={"source": file_name, "chars": len(content)}
                )
                if layer_callback: await layer_callback("soul", content)
                continue
            if layer_name == "daily_log":
                log_body, sources = self._read_recent_day_logs(2)
                sec = f"## 近期日志（今天 + 昨天）\n\n{log_body}"
                yield LoadChunk(
                    layer_name="daily_log", partial_content=sec, finished=True,
                    layer_meta={"source": ", ".join(sources), "chars": len(sec)}
                )
                if layer_callback: await layer_callback("daily_log", sec)
                continue
            if layer_name == "user_profile":
                raw = self._read_md(file_name)
                sec = f"## 关于当前用户\n{raw}"
                yield LoadChunk(
                    layer_name="user_profile", partial_content=sec, finished=True,
                    layer_meta={"source": file_name, "chars": len(sec)}
                )
                if layer_callback: await layer_callback("user_profile", sec)
                continue
            if layer_name == "agents_manual":
                content = self._read_md(file_name)
                yield LoadChunk(
                    layer_name="agents_manual", partial_content=content, finished=True,
                    layer_meta={"source": file_name, "chars": len(content)}
                )
                if layer_callback: await layer_callback("agents_manual", content)
                continue
            if layer_name == "long_term_memory":
                mem_raw = self._read_md(file_name)
                offset = 0
                while True:
                    chunk_entries, total = self._extract_memory_entries_paginated(mem_raw, offset, chunk_size)
                    if not chunk_entries:
                        break
                    chunk_text = "\n\n".join(chunk_entries)
                    finished = (offset + chunk_size) >= total
                    yield LoadChunk(
                        layer_name="long_term_memory", partial_content=chunk_text, finished=finished,
                        layer_meta={"source": file_name, "offset": offset, "limit": chunk_size, "total": total}
                    )
                    if layer_callback: await layer_callback("long_term_memory", chunk_text)
                    if finished:
                        break
                    offset += chunk_size
    def build_system_prompt(self, recent_memory_limit: int = 10) -> SystemPromptResult:
        """原有全量加载逻辑完全保留，兼容旧代码"""
        layers: list[MemoryLayer] = []
        parts: list[str] = []
        # Layer 3a: SOUL.md — 人格基调
        soul = self._read_md("SOUL.md")
        if soul:
            layers.append(MemoryLayer("soul", "SOUL.md", soul))
            parts.append(soul)
        # Layer 2 近端：每日日志
        log_body, log_sources = self._read_recent_day_logs(days=2)
        if log_body:
            section = f"## 近期日志（今天 + 昨天）\n\n{log_body}"
            layers.append(MemoryLayer("daily_log", ", ".join(log_sources), section))
            parts.append(section)
        # Layer 3b: USER.md — 用户画像
        user = self._read_md("USER.md")
        if user:
            section = f"## 关于当前用户\n{user}"
            layers.append(MemoryLayer("user_profile", "USER.md", section))
            parts.append(section)
        # Layer 3c: AGENTS.md — 操作规范
        agents = self._read_md("AGENTS.md")
        if agents:
            layers.append(MemoryLayer("agents_manual", "AGENTS.md", agents))
            parts.append(agents)
        # Layer 3d: MEMORY.md 近期条目
        memory_md = self._read_md("MEMORY.md")
        memory_entries = self._extract_memory_entries(memory_md, recent_memory_limit)
        if memory_entries:
            section = f"## 长期记忆（最近 {recent_memory_limit} 条）\n\n{memory_entries}"
            layers.append(MemoryLayer("long_term_memory", "MEMORY.md", section))
            parts.append(section)
        system_prompt = "\n\n---\n\n".join(parts)
        return SystemPromptResult(system_prompt=system_prompt, layers=layers)
    def get_memory_entry_count(self) -> int:
        """返回当前 MEMORY.md 中的条目数量"""
        memory_md = self._read_md("MEMORY.md")
        return len(re.findall(r"^### \[", memory_md, re.MULTILINE))
    def get_user_md_path(self) -> Path:
        return self.memory_dir / "USER.md"
    def get_memory_md_path(self) -> Path:
        return self.memory_dir / "MEMORY.md"