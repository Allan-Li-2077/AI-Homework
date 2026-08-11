"""
用户反馈收集器：在用户使用 Skill 的过程中，收集用户对生成结果的反馈。

核心思想：
  - 传统 Nudge 靠测试集发现 Skill 缺陷，需要人工设计测试集
  - 这里让用户在真实使用中发现问题并反馈，系统自动收集整理
  - 用户反馈比测试集更直接反映真实需求

使用方式：
  from skill_optimize.user_feedback_collector import UserFeedbackCollector
  collector = UserFeedbackCollector()
  collector.record(output, "这个单词卡片缺少使用场景举例")
"""

from datetime import datetime
from pathlib import Path
from typing import Optional
import json
import hashlib


class UserFeedback:
    """单条用户反馈"""

    def __init__(
        self,
        skill_name: str,
        user_input: str,
        generated_output: str,
        feedback_text: str,
        feedback_type: str = "suggestion",
        timestamp: Optional[str] = None,
    ):
        self.skill_name = skill_name
        self.user_input = user_input
        self.generated_output = generated_output
        self.feedback_text = feedback_text
        self.feedback_type = feedback_type  # suggestion | complaint | praise
        self.timestamp = timestamp or datetime.now().isoformat()
        self.id = self._generate_id()

    def _generate_id(self) -> str:
        content = f"{self.skill_name}:{self.user_input}:{self.feedback_text}:{self.timestamp}"
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "skill_name": self.skill_name,
            "user_input": self.user_input,
            "generated_output": self.generated_output,
            "feedback_text": self.feedback_text,
            "feedback_type": self.feedback_type,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserFeedback":
        fb = cls(
            skill_name=d["skill_name"],
            user_input=d["user_input"],
            generated_output=d["generated_output"],
            feedback_text=d["feedback_text"],
            feedback_type=d.get("feedback_type", "suggestion"),
            timestamp=d.get("timestamp"),
        )
        fb.id = d.get("id", fb.id)
        return fb


class UserFeedbackCollector:
    """
    收集用户反馈，支持多种来源：

    1. 显式反馈：用户主动说"缺少 XXX"
    2. 隐式反馈：用户修改了生成内容（说明不满意）
    3. 追问反馈：用户追问"能不能加上 XXX"

    反馈类型自动分类：
    - suggestion：用户建议添加内容（"可以加上 XXX"）
    - complaint：用户抱怨缺失（"缺少 XXX"、"没有 XXX"）
    - correction：用户纠正了内容
    - praise：用户表示满意（可用于确认 Skill 优点）
    """

    def __init__(self, storage_dir: str = None):
        if storage_dir is None:
            storage_dir = str(Path(__file__).parent / "outputs" / "user_feedback")
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._feedback_buffer: list[UserFeedback] = []

    def record(
        self,
        skill_name: str,
        user_input: str,
        generated_output: str,
        feedback_text: str,
        feedback_type: Optional[str] = None,
    ) -> UserFeedback:
        """
        记录一条用户反馈。

        如果不指定 feedback_type，会根据 feedback_text 自动推断：
        - 包含"缺少"/"没有"/"建议"/"可以加" → suggestion
        - 包含"错误"/"不对"/"纠正" → correction
        - 包含"很好"/"不错"/"满意" → praise
        """
        if feedback_type is None:
            feedback_type = self._infer_type(feedback_text)

        fb = UserFeedback(
            skill_name=skill_name,
            user_input=user_input,
            generated_output=generated_output,
            feedback_text=feedback_text,
            feedback_type=feedback_type,
        )
        self._feedback_buffer.append(fb)
        return fb

    def _infer_type(self, text: str) -> str:
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["缺少", "没有", "建议", "可以加", "建议加上", "能不能加"]):
            return "suggestion"
        if any(kw in text_lower for kw in ["错误", "不对", "纠正", "应该是"]):
            return "correction"
        if any(kw in text_lower for kw in ["很好", "不错", "满意", "棒"]):
            return "praise"
        return "suggestion"

    def record_from_implicit(
        self,
        skill_name: str,
        user_input: str,
        original_output: str,
        revised_output: str,
    ) -> UserFeedback:
        """
        记录隐式反馈：用户修改了生成内容。
        说明用户对 original_output 不满意。
        """
        feedback_text = f"用户修改了生成内容（原始: {original_output[:50]}...）"
        return self.record(
            skill_name=skill_name,
            user_input=user_input,
            generated_output=original_output,
            feedback_text=feedback_text,
            feedback_type="complaint",
        )

    def record_from_follow_up(
        self,
        skill_name: str,
        user_input: str,
        generated_output: str,
        follow_up_text: str,
    ) -> UserFeedback:
        """
        记录追问式反馈：用户在生成后追问"能不能加上 XXX"。
        """
        return self.record(
            skill_name=skill_name,
            user_input=user_input,
            generated_output=generated_output,
            feedback_text=f"追问补充：{follow_up_text}",
            feedback_type="suggestion",
        )

    def flush_to_disk(self, skill_name: Optional[str] = None):
        """
        将缓冲的反馈写入磁盘。
        按 skill_name 分文件存储，方便后续分析。
        """
        if not self._feedback_buffer:
            return

        by_skill: dict[str, list[dict]] = {}
        for fb in self._feedback_buffer:
            by_skill.setdefault(fb.skill_name, []).append(fb.to_dict())

        for name, entries in by_skill.items():
            if skill_name and name != skill_name:
                continue
            file_path = self.storage_dir / f"{name}_feedback.json"
            existing = []
            if file_path.exists():
                existing = json.loads(file_path.read_text(encoding="utf-8"))
            existing.extend(entries)
            file_path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        self._feedback_buffer.clear()
        print(f"  [UserFeedbackCollector] 已写入 {len(by_skill)} 个 Skill 的反馈")

    def get_feedback(self, skill_name: str) -> list[UserFeedback]:
        """读取某个 Skill 的所有反馈"""
        file_path = self.storage_dir / f"{skill_name}_feedback.json"
        if not file_path.exists():
            return []
        entries = json.loads(file_path.read_text(encoding="utf-8"))
        return [UserFeedback.from_dict(e) for e in entries]

    def get_all_feedback(self) -> dict[str, list[UserFeedback]]:
        """读取所有 Skill 的反馈"""
        result = {}
        for f in self.storage_dir.glob("*_feedback.json"):
            name = f.stem.replace("_feedback", "")
            result[name] = self.get_feedback(name)
        return result
