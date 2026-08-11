"""
Skill 优化器：分析 Agent 失败样本，用 LLM 重写 Skill 以提升效果。

自进化核心机制：
  1. Agent 用当前 Skill 回答问题
  2. 评估器判分，收集失败样本（哪些关键词没答对）
  3. 优化器拿到【失败样本 + 当前 Skill + 知识手册(ground truth)】
     → 对照知识手册找到正确答案 → 重写 Skill 让 Agent 下次能答对
  4. 新 Skill 覆盖旧 Skill，回到第 1 步再跑一轮

知识手册(travel_knowledge.md)的角色：
  - 相当于"标准答案参考书"
  - 优化器用它核对：Agent 答错的那道题，正确答案到底是什么
  - 然后把这个正确信息在新 Skill 里表达得更清晰、更突出

优化策略（双重目标）：
  A. 提升准确率：对照知识手册，修复 Skill 中导致 Agent 答错/遗漏的部分
  B. 降低 Token 消耗：精简冗余表述，散文→表格/列表
"""

import os
import re
import json
from pathlib import Path
from openai import OpenAI


OPTIMIZER_PROMPT = """你是一位 Skill 文档优化专家。你的任务是优化旅行指南 Skill，使其同时满足两个目标：

## 优化目标

### 目标 A：提升回答准确率
分析下方"失败样本"中 Agent 答错或遗漏的原因，对照"知识手册（判定标准）"中的正确信息，在新 Skill 中修复：
- 关键数字/信息被埋在冗长文字中 → 提取为独立条目或表格行
- 同类信息分散在不同段落 → 合并到一起
- 例外规则不够醒目 → 用 ⚠️ 或 **加粗** 标记
- 失败样本里标注了每道题"必须包含"的关键词 → 确保这些信息在新 Skill 中足够突出

### 目标 B：降低 Token 消耗（精简文档）
- 删除口语化废话："大家好"、"首先我们来聊聊"、"接下来我们说说"、"这个很重要"
- 将散文段落改为结构化列表或表格
- 删除重复信息（同一条信息在不同段落出现多次）
- 保留 frontmatter（--- 之间的 YAML 头），但更新 version 号

## 硬性约束
1. **所有事实信息必须与知识手册一致**（价格、天数、城市、汇率等数字以知识手册为准）
2. **不能丢失知识手册中 Skill 已覆盖的任何信息**
3. 不要添加知识手册中没有的新信息
4. 输出必须是完整的 SKILL.md 文件内容（含 frontmatter）

## 知识手册（判定标准，以此为准）
{ground_truth}

## 当前 Skill 文档（{char_count} 字符）
```
{current_skill}
```

## 失败样本分析（含标准答案关键词）
{failures_text}

## 输出格式
请严格按以下 JSON 格式输出：
{{
  "analysis": "对当前 Skill 问题的分析：哪些信息不够突出、哪些结构需要改进（200字以内）",
  "changes_summary": "本次主要做了哪些改动（100字以内）",
  "new_skill": "优化后的完整 SKILL.md 内容"
}}

只输出 JSON，不要有其他文字。"""


class SkillOptimizer:

    def __init__(self, skill_manager, evaluator, knowledge_path: str = None,
                 model: str = "deepseek-chat"):
        self.skill_manager = skill_manager
        self.evaluator = evaluator
        self.model = model
        # 加载知识手册作为 ground truth（优化器用它来核对正确答案）
        self.ground_truth = ""
        if knowledge_path:
            p = Path(knowledge_path)
            if p.exists():
                self.ground_truth = p.read_text(encoding="utf-8")
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )

    def optimize_one_round(self, agent, skill_name: str = None) -> dict:
        """
        执行一轮优化：
        1. 跑评估，收集失败样本
        2. 调 LLM 生成优化后的 Skill
        3. 保存到磁盘

        返回：
        {
            "success": bool,
            "analysis": str,
            "changes": str,
            "failures_before": int,
            "old_char_count": int,
            "new_char_count": int | None,
        }
        """
        # 确定要优化的 Skill
        skills = self.skill_manager.load_all()
        if not skills:
            return {"success": False, "analysis": "无 Skill 可优化"}
        if skill_name is None:
            skill_name = list(skills.keys())[0]
        current_content = skills[skill_name]

        # 跑评估收集失败样本
        eval_result = self.evaluator.run_eval(agent)
        failed_details = [d for d in eval_result["details"] if not d["passed"]]

        if not failed_details:
            return {
                "success": True,
                "analysis": "所有题目已通过，无需优化",
                "changes": "无改动",
                "failures_before": 0,
                "old_char_count": len(current_content),
                "new_char_count": len(current_content),
            }

        # 构建 LLM 提示（传入 ground truth 知识手册）
        failures_text = self._format_failures(failed_details)
        prompt = OPTIMIZER_PROMPT.format(
            current_skill=current_content,
            char_count=len(current_content),
            failures_text=failures_text,
            ground_truth=self.ground_truth or "（未提供知识手册）",
        )

        # 调用 LLM
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=4000,
        )
        raw = resp.choices[0].message.content.strip()

        # 解析 JSON
        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return {"success": False, "analysis": "LLM 输出无法解析", "failures_before": len(failed_details)}
            data = json.loads(match.group())
            new_skill = data.get("new_skill", "")
            if not new_skill:
                return {"success": False, "analysis": "LLM 未生成新 Skill", "failures_before": len(failed_details)}

            # 保存优化后的 Skill
            reason = f"优化轮次: 修复{len(failed_details)}个失败 | {data.get('changes_summary', '')[:80]}"
            self.skill_manager.save(skill_name, new_skill, reason=reason)

            return {
                "success": True,
                "analysis": data.get("analysis", ""),
                "changes": data.get("changes_summary", ""),
                "failures_before": len(failed_details),
                "old_char_count": len(current_content),
                "new_char_count": len(new_skill),
            }

        except json.JSONDecodeError as e:
            return {"success": False, "analysis": f"JSON 解析失败: {e}", "failures_before": len(failed_details)}

    def iterative_optimize(self, agent, skill_name: str = None,
                           max_rounds: int = 3, patience: int = 2) -> list:
        """
        迭代优化：每轮优化后重新评估，直到全部通过或连续 patience 轮无改善。

        返回每轮结果列表：
        [{round, eval_before, optimization, eval_after}, ...]
        """
        results = []
        prev_passed = -1
        no_improve_count = 0

        for r in range(1, max_rounds + 1):
            print(f"\n{'━' * 64}")
            print(f"  第 {r}/{max_rounds} 轮优化")
            print(f"{'━' * 64}")

            # 1. 优化前评估
            agent.reset_stats()
            eval_before = self.evaluator.run_eval(agent)
            eval_before.pop("details", None)  # 节省内存
            print(f"  优化前: 通过率 {eval_before['pass_rate']:.0%}, 均分 {eval_before['avg_score']:.0f}")

            # 2. 执行优化
            opt_result = self.optimize_one_round(agent, skill_name)
            if not opt_result["success"]:
                print(f"  ⚠ 优化失败: {opt_result['analysis']}")
                break

            print(f"  优化分析: {opt_result['analysis'][:100]}")
            print(f"  改动说明: {opt_result['changes'][:100]}")
            if opt_result["new_char_count"]:
                delta = opt_result["new_char_count"] - opt_result["old_char_count"]
                pct = delta / opt_result["old_char_count"] * 100 if opt_result["old_char_count"] else 0
                print(f"  文档长度: {opt_result['old_char_count']} → {opt_result['new_char_count']} 字符 ({pct:+.0f}%)")

            # 3. 优化后评估
            agent.reset_stats()
            eval_after = self.evaluator.run_eval(agent)
            eval_after.pop("details", None)
            print(f"  优化后: 通过率 {eval_after['pass_rate']:.0%}, 均分 {eval_after['avg_score']:.0f}")

            results.append({
                "round": r,
                "eval_before": eval_before,
                "optimization": opt_result,
                "eval_after": eval_after,
            })

            # 4. 判断是否继续
            curr_passed = eval_after["passed_count"]
            if curr_passed == eval_before["total_questions"]:
                print(f"  ✓ 全部通过！停止优化")
                break
            if curr_passed <= prev_passed:
                no_improve_count += 1
                if no_improve_count >= patience:
                    print(f"  ⚠ 连续 {patience} 轮无改善，停止")
                    break
            else:
                no_improve_count = 0
            prev_passed = curr_passed

        return results

    def _format_failures(self, failed: list) -> str:
        """格式化失败样本，附带评估集中标注的标准答案关键词"""
        lines = []
        for i, d in enumerate(failed, 1):
            q = self.evaluator.questions.get(d['qid'], {})
            lines.append(f"[{i}] 题目(Q{d['qid']}, 类别={d['category']}): {d['question']}")
            lines.append(f"    Agent错误回答: {d['answer'][:150]}...")
            lines.append(f"    得分: {d['score']}  失败原因: {'; '.join(d['failures'][:3])}")
            # 把评估集中的标准关键词也展示出来，优化器知道"正确答案应该包含什么"
            must_inc = q.get("must_include", [])
            if must_inc:
                lines.append(f"    ✅ 标准答案须含: {must_inc}")
            must_exc = q.get("must_exclude", [])
            if must_exc:
                lines.append(f"    ❌ 标准答案禁含: {must_exc}")
        return "\n".join(lines)
