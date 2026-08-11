"""
Skill 优化管理器：协调整个用户反馈驱动的 Skill 优化流程。

使用流程：
  1. 收集阶段：用户使用 Skill 并产生反馈，Collector 记录
  2. 分析阶段：Analyzer 分析反馈模式
  3. 优化阶段：Optimizer 生成并执行 Skill 改进
  4. 验证阶段：用户再次使用，检验改进效果

使用方式：
  from skill_optimize.skill_optimize_manager import SkillOptimizeManager

  manager = SkillOptimizeManager(skills_dir="skills-origin")
  manager.record_feedback("flashcard", "apple", "['苹果']", "缺少使用场景举例")
  manager.run_optimization()  # 触发分析和优化
"""

from pathlib import Path
from typing import Optional
import os
# skill_manager 在 src/ 目录，添加父目录到 sys.path 以便导入
import sys
from pathlib import Path as P
_skill_manager_path = str(P(__file__).parent.parent / "src")
if _skill_manager_path not in sys.path:
    sys.path.insert(0, _skill_manager_path)
from skill_manager import SkillManager

from .user_feedback_collector import UserFeedbackCollector, UserFeedback
from .feedback_analyzer import FeedbackAnalyzer, FeedbackPattern
from .skill_optimizer import SkillOptimizer, OptimizeAction


class SkillOptimizeManager:
    """
    用户反馈驱动的 Skill 优化管理器。

    与 Nudge 机制的区别：

    | 维度 | Nudge（测试集驱动） | SkillOptimize（用户反馈驱动） |
    |------|-------------------|---------------------------|
    | 触发 | 块内测试失败 | 用户主动反馈 |
    | 反馈来源 | 评估器判定 | 用户真实体验 |
    | 设计成本 | 需要设计测试集 | 无需测试集 |
    | 进化时机 | 块结束时批量处理 | 可实时或批量 |
    | 反馈类型 | 对/错 | 建议/抱怨/纠正/表扬 |
    """

    def __init__(
        self,
        skills_dir: str,
        feedback_storage: str = None,
        skill_versions_dir: str = None,
    ):
        # 默认输出到 skill_optimize/outputs/ 目录下
        if feedback_storage is None:
            feedback_storage = str(Path(__file__).parent / "outputs" / "user_feedback")
        if skill_versions_dir is None:
            skill_versions_dir = str(Path(__file__).parent / "outputs" / "skill_versions")

        self.skills_dir = Path(skills_dir)
        self.skill_manager = SkillManager(
            skills_dir=str(skills_dir),
            versions_dir=skill_versions_dir,
        )
        self.collector = UserFeedbackCollector(storage_dir=feedback_storage)
        self.analyzer = FeedbackAnalyzer()
        self.optimizer: Optional[SkillOptimizer] = None

    def set_llm_optimizer(self, api_key: Optional[str] = None, model: str = "deepseek-chat"):
        """设置 LLM 驱动的优化器（可选，默认用规则分析）"""
        if api_key is None:
            api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.optimizer = SkillOptimizer(
            skill_manager=self.skill_manager,
            model=model,
            api_key=api_key,
        )

    def record_feedback(
        self,
        skill_name: str,
        user_input: str,
        generated_output: str,
        feedback_text: str,
        feedback_type: Optional[str] = None,
    ):
        """
        记录一条用户反馈。

        示例：
          manager.record_feedback(
              skill_name="flashcard",
              user_input="apple",
              generated_output="['苹果']",
              feedback_text="缺少使用场景举例，能造个句子吗？",
          )
        """
        self.collector.record(
            skill_name=skill_name,
            user_input=user_input,
            generated_output=generated_output,
            feedback_text=feedback_text,
            feedback_type=feedback_type,
        )

    def record_implicit_feedback(
        self,
        skill_name: str,
        user_input: str,
        original_output: str,
        revised_output: str,
    ):
        """
        记录隐式反馈：用户修改了生成内容。

        说明用户对 original_output 不满意，revised_output 是用户修改后的版本。
        """
        self.collector.record_from_implicit(
            skill_name=skill_name,
            user_input=user_input,
            original_output=original_output,
            revised_output=revised_output,
        )

    def run_optimization(
        self,
        skill_name: str,
        use_llm: bool = False,
        min_feedback_count: int = 3,
        max_actions: int = 2,
    ) -> dict:
        """
        对指定 Skill 运行完整的优化流程。

        Args:
            skill_name: 要优化的 Skill 名称
            use_llm: 是否使用 LLM 驱动的分析（更智能但更贵）
            min_feedback_count: 最少收集到多少条反馈才触发优化
            max_actions: 最多生成多少个优化操作

        Returns:
            优化结果统计，包含分析结果和执行结果
        """
        # 1. 获取反馈
        feedback_list = self.collector.get_feedback(skill_name)

        if len(feedback_list) < min_feedback_count:
            print(f"  [SkillOptimize] {skill_name} 只有 {len(feedback_list)} 条反馈，需要 >= {min_feedback_count} 才触发优化")
            return {
                "status": "skipped",
                "reason": f"反馈数量不足（{len(feedback_list)}/{min_feedback_count}）",
                "skill_name": skill_name,
            }

        # 2. 持久化新反馈
        self.collector.flush_to_disk(skill_name)

        # 3. 分析反馈模式
        patterns = self.analyzer.analyze(feedback_list)
        if not patterns:
            print(f"  [SkillOptimize] {skill_name} 无法识别反馈模式，跳过优化")
            return {
                "status": "skipped",
                "reason": "无法识别反馈模式",
                "skill_name": skill_name,
            }

        # 4. 获取当前 Skill 内容
        current_skill = self.skill_manager.get(skill_name)
        if current_skill is None:
            print(f"  [SkillOptimize] Skill '{skill_name}' 不存在，跳过")
            return {
                "status": "skipped",
                "reason": "Skill 不存在",
                "skill_name": skill_name,
            }

        # 5. 生成优化操作
        if use_llm and self.optimizer:
            actions = self.optimizer.generate_actions(
                skill_name=skill_name,
                patterns=patterns,
                skill_content=current_skill,
                feedback_list=feedback_list,
            )
        else:
            from .skill_optimizer import RuleBasedOptimizer
            rule_optimizer = RuleBasedOptimizer()
            actions = rule_optimizer.generate_from_patterns(patterns, current_skill)
            for action in actions:
                action.skill_name = skill_name

        # 限制操作数量
        actions = actions[:max_actions]

        if not actions:
            print(f"  [SkillOptimize] {skill_name} 无需优化操作")
            return {
                "status": "no_actions",
                "patterns": [p.to_dict() for p in patterns],
                "skill_name": skill_name,
            }

        # 6. 执行优化
        if self.optimizer:
            results = self.optimizer.apply_actions(actions)
        else:
            results = {"patched": 0, "created": 0, "failed": 0, "details": []}
            for action in actions:
                if action.action == "patch":
                    success = self.skill_manager.patch(
                        skill_name=action.skill_name,
                        old_text=action.old_text,
                        new_text=action.new_text,
                        reason=action.reason,
                    )
                    if success:
                        results["patched"] += 1
                    else:
                        results["failed"] += 1

        print(f"  [SkillOptimize] {skill_name} 优化完成：patched={results['patched']}, created={results['created']}, failed={results['failed']}")

        return {
            "status": "success",
            "patterns": [p.to_dict() for p in patterns],
            "actions": [a.to_dict() for a in actions],
            "results": results,
            "skill_name": skill_name,
            "feedback_count": len(feedback_list),
        }

    def run_all_optimizations(
        self,
        use_llm: bool = False,
        min_feedback_count: int = 3,
    ) -> dict:
        """
        对所有有足够反馈的 Skill 运行优化。

        Returns:
            各 Skill 的优化结果统计
        """
        all_feedback = self.collector.get_all_feedback()
        results = {}

        for skill_name in all_feedback:
            result = self.run_optimization(
                skill_name=skill_name,
                use_llm=use_llm,
                min_feedback_count=min_feedback_count,
            )
            results[skill_name] = result

        return results

    # =========================================================================
    # 在线优化：用户反馈后立即处理
    # =========================================================================

    def process_feedback_now(
        self,
        skill_name: str,
        user_input: str,
        generated_output: str,
        feedback_text: str,
        use_llm: bool = False,
        preview: bool = False,
    ) -> dict:
        """
        在线优化：用户反馈后处理。

        Args:
            skill_name: Skill 名称
            user_input: 用户输入（如 "apple"）
            generated_output: 生成的输出
            feedback_text: 用户反馈（如"缺少使用场景举例"）
            use_llm: 是否使用 LLM 分析（更智能但更慢/更贵）
            preview: 如果为 True，只返回改动预览，不实际执行

        Returns:
            优化结果。如果 preview=True，返回预览内容但不执行。

        示例：
            # 预览模式（不执行）
            result = manager.process_feedback_now(
                skill_name="flashcard",
                user_input="apple",
                generated_output="...",
                feedback_text="缺少使用场景举例",
                preview=True,  # 只预览，不执行
            )
            if result["status"] == "preview":
                print("改动预览：")
                print(result["diff"])

            # 执行模式
            result = manager.process_feedback_now(
                skill_name="flashcard",
                user_input="apple",
                generated_output="...",
                feedback_text="缺少使用场景举例",
            )
            if result["status"] == "updated":
                print("Skill 已更新")
        """
        # 1. 记录反馈
        feedback = self.collector.record(
            skill_name=skill_name,
            user_input=user_input,
            generated_output=generated_output,
            feedback_text=feedback_text,
        )

        # 2. 获取 Skill 内容
        current_skill = self.skill_manager.get(skill_name)
        if current_skill is None:
            return {
                "status": "skipped",
                "reason": f"Skill '{skill_name}' 不存在",
                "skill_name": skill_name,
            }

        # 3. 分析这条反馈
        analyzer = FeedbackAnalyzer()
        patterns = analyzer.analyze([feedback])

        if not patterns:
            return {
                "status": "no_pattern",
                "reason": "无法理解反馈内容",
                "feedback": feedback_text,
            }

        pattern = patterns[0]  # 取第一个匹配的模式

        # 4. 生成优化操作
        if use_llm and self.optimizer:
            # LLM 模式：更智能但需要 API 调用
            actions = self.optimizer.generate_actions(
                skill_name=skill_name,
                patterns=[pattern],
                skill_content=current_skill,
                feedback_list=[feedback],
            )
        else:
            # 规则模式：快速但只能处理预定义模式
            from .skill_optimizer import RuleBasedOptimizer
            rule_optimizer = RuleBasedOptimizer()
            actions = rule_optimizer.generate_from_patterns([pattern], current_skill)
            for action in actions:
                action.skill_name = skill_name

        if not actions:
            return {
                "status": "no_action",
                "reason": f"反馈类型 '{pattern.category}' 无对应优化规则",
                "pattern": pattern.category,
            }

        # 5. 预览模式：只返回改动，不执行
        if preview:
            action = actions[0]
            diff = self._generate_diff(current_skill, action)
            return {
                "status": "preview",
                "feedback": feedback_text,
                "pattern": pattern.category,
                "action": action.action,
                "old_text": action.old_text,
                "new_text": action.new_text,
                "reason": action.reason,
                "diff": diff,
            }

        # 6. 执行更新
        action = actions[0]  # 取第一个操作
        if action.action == "patch":
            success = self.skill_manager.patch(
                skill_name=skill_name,
                old_text=action.old_text,
                new_text=action.new_text,
                reason=f"[用户反馈] {feedback_text}",
            )
        elif action.action == "create":
            success = self.skill_manager.create(
                skill_name=action.skill_name,
                content=action.content,
                reason=f"[用户反馈] {feedback_text}",
            )
        else:
            success = False

        if success:
            return {
                "status": "updated",
                "reason": action.reason,
                "pattern": pattern.category,
                "action": action.action,
                "feedback": feedback_text,
            }
        else:
            return {
                "status": "failed",
                "reason": "Skill 更新失败（old_text 可能已变化）",
                "pattern": pattern.category,
            }

    def chat_optimize(
        self,
        skill_name: str,
        user_message: str,
        generated_output: str,
        use_llm: bool = False,
    ) -> dict:
        """
        对话式优化：根据用户的一句话，理解意图并更新 Skill。

        这是更自然的交互方式：
        - 用户不需要说特定格式的反馈
        - 系统理解用户说的内容，判断是否需要更新 Skill
        - 自动处理新增规则、修改规则等

        Args:
            skill_name: Skill 名称
            user_message: 用户说的一句话（如"能不能加个使用场景举例？"）
            generated_output: 生成的输出
            use_llm: 是否使用 LLM 理解（更智能）

        Returns:
            优化结果

        示例：
            result = manager.chat_optimize(
                skill_name="flashcard",
                user_message="这些卡片缺少使用场景举例，能加个例句吗？",
                generated_output="['apple', '苹果']",
                use_llm=True,  # 用 LLM 理解用户意图
            )
        """
        # 1. 理解用户意图（简单规则匹配）
        feedback_text = self._extract_feedback_from_message(user_message)
        feedback_type = self._infer_feedback_type(user_message)

        # 2. 记录反馈
        feedback = self.collector.record(
            skill_name=skill_name,
            user_input="",
            generated_output=generated_output,
            feedback_text=feedback_text,
            feedback_type=feedback_type,
        )

        # 3. 获取 Skill 内容
        current_skill = self.skill_manager.get(skill_name)
        if current_skill is None:
            return {
                "status": "skipped",
                "reason": f"Skill '{skill_name}' 不存在",
            }

        # 4. 分析并生成更新
        if use_llm and self.optimizer:
            analyzer = FeedbackAnalyzer()
            patterns = analyzer.analyze([feedback])
            if not patterns:
                return {"status": "no_pattern", "reason": "无法理解"}

            actions = self.optimizer.generate_actions(
                skill_name=skill_name,
                patterns=patterns,
                skill_content=current_skill,
                feedback_list=[feedback],
            )
        else:
            # 规则模式
            from .skill_optimizer import RuleBasedOptimizer
            analyzer = FeedbackAnalyzer()
            patterns = analyzer.analyze([feedback])
            if not patterns:
                return {"status": "no_pattern", "reason": "无法理解"}

            rule_optimizer = RuleBasedOptimizer()
            actions = rule_optimizer.generate_from_patterns(patterns, current_skill)
            for action in actions:
                action.skill_name = skill_name

        if not actions:
            return {
                "status": "no_action",
                "reason": "无需更新 Skill",
                "message": user_message,
            }

        # 5. 执行
        action = actions[0]
        try:
            if action.action == "patch":
                success = self.skill_manager.patch(
                    skill_name=skill_name,
                    old_text=action.old_text,
                    new_text=action.new_text,
                    reason=f"[用户] {user_message}",
                )
            else:
                success = False

            return {
                "status": "updated" if success else "failed",
                "reason": action.reason,
                "message": user_message,
            }
        except Exception as e:
            return {
                "status": "error",
                "reason": str(e),
                "message": user_message,
            }

    def _extract_feedback_from_message(self, message: str) -> str:
        """从用户消息中提取反馈内容"""
        # 去掉语气词和问句，提取核心诉求
        message = message.strip()
        # 简单处理：如果消息已经是一个反馈描述，直接返回
        return message

    def _infer_feedback_type(self, message: str) -> str:
        """推断反馈类型"""
        message_lower = message.lower()
        if any(kw in message_lower for kw in ["缺少", "没有", "建议", "可以加", "能不能加"]):
            return "suggestion"
        if any(kw in message_lower for kw in ["错误", "不对", "纠正"]):
            return "correction"
        if any(kw in message_lower for kw in ["很好", "不错", "满意"]):
            return "praise"
        return "suggestion"

    def _generate_diff(self, current_skill: str, action) -> str:
        """生成改动预览文本"""
        if action.action == "patch":
            old = action.old_text or ""
            new = action.new_text or ""
            return f"""【Patch 预览】
- 删除：
{old}

+ 新增：
{new}"""
        elif action.action == "create":
            return f"""【Create 新 Skill】
名称: {action.skill_name}
内容:
{action.content}"""
        return "【未知操作】"

    def preview_and_apply(
        self,
        skill_name: str,
        user_input: str,
        generated_output: str,
        feedback_text: str,
        use_llm: bool = False,
    ) -> dict:
        """
        先预览改动，用户确认后再执行。

        这是一个便捷方法，相当于：
        1. 先 preview=True 预览
        2. 用户确认
        3. 再次调用时传入 apply=True

        Args:
            skill_name: Skill 名称
            user_input: 用户输入
            generated_output: 生成结果
            feedback_text: 用户反馈
            use_llm: 是否使用 LLM

        Returns:
            预览结果或执行结果

        示例：
            # 第一次调用，获取预览
            preview = manager.preview_and_apply(
                skill_name="flashcard",
                user_input="apple",
                generated_output="...",
                feedback_text="缺少使用场景举例",
            )
            if preview["status"] == "preview":
                print(preview["diff"])
                # 用户确认后...

            # 第二次调用，执行改动
            result = manager.preview_and_apply(
                skill_name="flashcard",
                user_input="apple",
                generated_output="...",
                feedback_text="缺少使用场景举例",
                apply=True,
            )
        """
        return self.process_feedback_now(
            skill_name=skill_name,
            user_input=user_input,
            generated_output=generated_output,
            feedback_text=feedback_text,
            use_llm=use_llm,
            preview=True,
        )

    def rollback(self, skill_name: str, version: int = None) -> dict:
        """
        回滚 Skill 到指定版本。

        Args:
            skill_name: Skill 名称
            version: 版本号。如果为 None，回滚到上一个版本。

        Returns:
            回滚结果

        示例：
            # 回滚到上一个版本
            result = manager.rollback("flashcard")

            # 回滚到指定版本
            result = manager.rollback("flashcard", version=3)

            if result["success"]:
                print(f"已回滚到 v{result['version']}")
            else:
                print(f"回滚失败: {result['reason']}")
        """
        history = self.skill_manager.get_version_history(skill_name)
        if not history:
            return {"success": False, "reason": "该 Skill 没有版本历史"}

        if version is None:
            # 回滚到上一个版本
            if len(history) < 2:
                return {"success": False, "reason": "没有可回滚的版本"}
            target_version = history[-2]["version"]
        else:
            target_version = version

        success = self.skill_manager.rollback(skill_name, target_version)
        if success:
            return {
                "success": True,
                "skill_name": skill_name,
                "version": target_version,
                "message": f"已回滚到 v{target_version}",
            }
        else:
            return {"success": False, "reason": "回滚执行失败"}

    def get_version_history(self, skill_name: str) -> list:
        """获取 Skill 的版本历史"""
        return self.skill_manager.get_version_history(skill_name)

    def get_optimization_summary(self, skill_name: str) -> dict:
        """
        获取某个 Skill 的优化摘要（反馈数量、模式分布等）
        """
        feedback_list = self.collector.get_feedback(skill_name)
        patterns = self.analyzer.analyze(feedback_list)

        return {
            "skill_name": skill_name,
            "total_feedback": len(feedback_list),
            "pattern_count": len(patterns),
            "top_patterns": [
                {"category": p.category, "count": p.count, "suggestion": p.suggestion}
                for p in patterns[:3]
            ],
            "feedback_breakdown": {
                "suggestion": sum(1 for f in feedback_list if f.feedback_type == "suggestion"),
                "complaint": sum(1 for f in feedback_list if f.feedback_type == "complaint"),
                "correction": sum(1 for f in feedback_list if f.feedback_type == "correction"),
                "praise": sum(1 for f in feedback_list if f.feedback_type == "praise"),
            },
        }


# 便捷函数：快速运行一个反馈驱动的优化周期
def quick_optimize(
    skill_name: str,
    skill_content: str,
    feedback_list: list[dict],
    skill_manager: SkillManager,
    use_llm: bool = False,
    api_key: Optional[str] = None,
) -> dict:
    """
    快速优化：输入 Skill 内容和反馈列表，输出优化后的 Skill 内容。

    Args:
        skill_name: Skill 名称
        skill_content: Skill 完整内容
        feedback_list: 反馈列表，每项包含 feedback_text
        skill_manager: SkillManager 实例
        use_llm: 是否使用 LLM
        api_key: DeepSeek API Key

    Returns:
        包含 analysis 和 actions 的结果

    示例：
        result = quick_optimize(
            skill_name="flashcard",
            skill_content=skill_md_text,
            feedback_list=[
                {"feedback_text": "缺少使用场景举例", "feedback_type": "suggestion"},
                {"feedback_text": "建议加上英式美式发音对比", "feedback_type": "suggestion"},
            ],
            skill_manager=sm,
            use_llm=True,
            api_key="sk-...",
        )
    """
    # 构建 UserFeedback 对象
    feedbacks = []
    for fb in feedback_list:
        feedbacks.append(UserFeedback(
            skill_name=skill_name,
            user_input=fb.get("user_input", ""),
            generated_output=fb.get("generated_output", ""),
            feedback_text=fb["feedback_text"],
            feedback_type=fb.get("feedback_type", "suggestion"),
        ))

    # 分析
    analyzer = FeedbackAnalyzer()
    patterns = analyzer.analyze(feedbacks)

    if not patterns:
        return {"status": "no_patterns", "patterns": []}

    # 生成操作
    if use_llm and api_key:
        optimizer = SkillOptimizer(skill_manager=skill_manager, api_key=api_key)
        actions = optimizer.generate_actions(
            skill_name=skill_name,
            patterns=patterns,
            skill_content=skill_content,
            feedback_list=feedbacks,
        )
    else:
        from .skill_optimizer import RuleBasedOptimizer
        rule_optimizer = RuleBasedOptimizer()
        actions = rule_optimizer.generate_from_patterns(patterns, skill_content)
        for action in actions:
            action.skill_name = skill_name

    # 执行
    results = {"status": "success", "actions": [], "patterns": [p.to_dict() for p in patterns]}

    if use_llm and api_key:
        exec_results = optimizer.apply_actions(actions)
        results["execution"] = exec_results
    else:
        for action in actions:
            if action.action == "patch":
                success = skill_manager.patch(
                    skill_name=action.skill_name,
                    old_text=action.old_text,
                    new_text=action.new_text,
                    reason=action.reason,
                )
                results["actions"].append({
                    "action": "patch",
                    "skill_name": action.skill_name,
                    "success": success,
                })

    return results
