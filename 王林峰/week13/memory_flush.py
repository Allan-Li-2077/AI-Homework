# memory_flush.py 新增核心渐进接口
class MemoryFlusher:
    # ... 原有初始化、辅助函数保留 ...
    async def flush_progressive(self, messages: list[dict], session_id: int, harness_db: SessionDB):
        """
        Harness 专用渐进分步 Flush 生成器，每一步执行完成返回状态，支持中断续跑
        yield {"step": str, "data": dict, "finished": bool}
        """
        conversation = self._format_conversation(messages)
        if not conversation.strip():
            yield {"step": "init", "data": {"error": "会话为空"}, "finished": True}
            return
        # 读取已有断点，判断从哪一步恢复
        checkpoints = harness_db.get_checkpoint(session_id)
        done_steps = {cp["step"] for cp in checkpoints if cp["status"] == "done"}
        result = FlushResult(session_id=session_id)
        # Step1：提取更新用户画像
        if "pass1" not in done_steps:
            user_updates = self._extract_and_update_user(conversation)
            result.user_updates = user_updates
            harness_db.save_checkpoint(session_id, "pass1", "done", {"user_updates": user_updates})
            yield {"step": "pass1", "data": {"user_updates": user_updates}, "finished": False}
        # Step2：提取长期记忆条目
        if "pass2" not in done_steps:
            new_entries = self._extract_memory_entries(conversation)
            if new_entries:
                self._append_to_memory_md(new_entries)
                self._append_to_daily_log(new_entries, session_id)
            result.new_memory_entries = new_entries
            harness_db.save_checkpoint(session_id, "pass2", "done", {"new_entries": new_entries})
            yield {"step": "pass2", "data": {"new_entries": new_entries}, "finished": False}
        # Step3：向量+FTS写入
        if "pass3" not in done_steps:
            new_entries = result.new_memory_entries
            count = 0
            if new_entries:
                count = self.vs.add_entries(new_entries)
                self.fts.add_entries(new_entries)
            result.vectorized_count = count
            harness_db.save_checkpoint(session_id, "pass3", "done", {"vectorized": count})
            yield {"step": "pass3", "data": {"vectorized_count": count}, "finished": False}
        # Step Compaction（按需执行）
        entry_count = self.loader.get_memory_entry_count()
        if entry_count >= self.compaction_threshold and "compact" not in done_steps:
            before, after = self._compact_memory()
            result.compacted = True
            result.compaction_before = before
            result.compaction_after = after
            harness_db.save_checkpoint(session_id, "compact", "done", {"before": before, "after": after})
            yield {"step": "compact", "data": {"before": before, "after": after}, "finished": False}
        # 全部完成
        harness_db.mark_flushed(session_id)
        harness_db.clear_checkpoints(session_id)
        yield {"step": "all_done", "data": result.__dict__, "finished": True}