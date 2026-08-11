"""
Skill 优化器：根据用户反馈生成 Skill 的改进方案。

核心工作：
  1. 接收反馈分析结果（patterns）
  2. 结合当前 Skill 内容，生成具体的 patch/create 方案
  3. 遵循最小改动原则，每次只改 1-2 处

使用方式：
  from skill_optimize.skill_optimizer import SkillOptimizer
  optimizer = SkillOptimizer(skill_manager)
  actions = optimizer.generate_actions(skill_name, patterns, current_skill)
"""

import os
import re
import json
from pathlib import Path
from typing import Optional
import sys
_skill_manager_path = str(Path(__file__).parent.parent / "src")
if _skill_manager_path not in sys.path:
    sys.path.insert(0, _skill_manager_path)
from skill_manager import SkillManager


# Skill 优化的系统提示词
SKILL_OPTIMIZER_SYSTEM = """你是 Skill 优化专家。你根据用户反馈改进 Skill，让下次生成结果更符合用户期望。

## 核心原则

1. **最小改动**：每次最多修改 1-2 处，不要重写整个 Skill
2. **精确替换**：old_text 必须精确匹配 Skill 中的原文
3. **保留优点**：不要删除用户满意的部分
4. **聚焦高频**：优先处理出现次数多的反馈类别

## 用户反馈类型

- suggestion：用户建议添加内容
- complaint：用户抱怨缺失
- correction：用户纠正了错误
- praise：用户表示满意（确认这个方向是对的）

## Skill 结构参考

Skill 文件格式：
```markdown
---
name: xxx
description: 简短描述
version: X
---

# 标题

内容正文...
```

## 输出格式

只输出 JSON，不要有其他文字：
```json
{
  "analysis": "本次优化的分析（1-2句话）",
  "actions": [
    {
      "action": "patch",
      "skill_name": "xxx",
      "reason": "修复哪个反馈的问题",
      "old_text": "精确的原始文本（要改的那几行）",
      "new_text": "替换后的文本"
    }
  ]
}
```

注意：输出必须是合法的 JSON，不要用多余的转义字符。

如果没有需要改进的地方，actions 数组留空。"""


SKILL_OPTIMIZER_USER = """## 用户反馈分析结果

{patterns_text}

## 当前 Skill 内容
```markdown
{skill_content}
```

## 用户原始反馈（参考）

{feedback_text}

请根据反馈分析结果，给出最小必要的 Skill 改进方案。"""


class OptimizeAction:
    """一次 Skill 操作（patch 或 create）"""

    def __init__(
        self,
        action: str,
        skill_name: str,
        reason: str,
        old_text: Optional[str] = None,
        new_text: Optional[str] = None,
        content: Optional[str] = None,
    ):
        self.action = action  # "patch" or "create"
        self.skill_name = skill_name
        self.reason = reason
        self.old_text = old_text
        self.new_text = new_text
        self.content = content

    def to_dict(self) -> dict:
        d = {
            "action": self.action,
            "skill_name": self.skill_name,
            "reason": self.reason,
        }
        if self.action == "patch":
            d["old_text"] = self.old_text
            d["new_text"] = self.new_text
        else:
            d["content"] = self.content
        return d


class SkillOptimizer:
    """
    基于用户反馈优化 Skill 的优化器。

    与 BackgroundReviewer 的区别：
    | 维度 | BackgroundReviewer | SkillOptimizer |
    |------|-------------------|---------------|
    | 输入 | 测试集失败样本 | 用户真实反馈 |
    | 触发 | 块内失败题 | 用户主动反馈 |
    | 反馈类型 | 对错判定 | 建议/抱怨/纠正 |
    """

    def __init__(
        self,
        skill_manager: SkillManager,
        model: str = "deepseek-chat",
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
    ):
        self.skill_manager = skill_manager
        self.model = model
        if api_key:
            os.environ["DEEPSEEK_API_KEY"] = api_key
        from openai import OpenAI
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY", api_key or ""),
            base_url=base_url,
        )
        self.last_analysis = ""

    def generate_actions(
        self,
        skill_name: str,
        patterns: list,
        skill_content: str,
        feedback_list: Optional[list] = None,
    ) -> list[OptimizeAction]:
        """
        根据反馈模式生成 Skill 操作列表。

        Args:
            skill_name: 要优化的 Skill 名称
            patterns: FeedbackAnalyzer 输出的模式列表
            skill_content: Skill 的完整内容
            feedback_list: 可选，原始反馈列表（用于上下文）

        Returns:
            OptimizeAction 列表
        """
        # 构建分析结果文本
        patterns_text = self._format_patterns(patterns)

        # 构建原始反馈文本
        feedback_text = ""
        if feedback_list:
            feedback_text = "\n".join(
                f"- [{fb.feedback_type}] {fb.feedback_text}"
                for fb in feedback_list[:10]
            )

        # 调用 LLM 生成优化方案
        system_msg = SKILL_OPTIMIZER_SYSTEM
        user_msg = SKILL_OPTIMIZER_USER.format(
            patterns_text=patterns_text,
            skill_content=skill_content,
            feedback_text=feedback_text or "（无原始反馈）",
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=3000,
        )

        raw = response.choices[0].message.content.strip()
        return self._parse_actions(raw, skill_name)

    def _format_patterns(self, patterns: list) -> str:
        """将模式列表格式化为文本"""
        lines = []
        for i, p in enumerate(patterns, 1):
            lines.append(f"### 模式 {i}：{p.category}（出现 {p.count} 次）")
            lines.append(f"建议：{p.suggestion}")
            lines.append(f"涉及 Skill 部分：{p.skill_section}")
            if p.examples:
                lines.append("典型反馈：")
                for ex in p.examples[:2]:
                    if isinstance(ex, dict):
                        lines.append(f"  - {ex.get('feedback', str(ex))}")
                    else:
                        lines.append(f"  - {ex}")
            lines.append("")
        return "\n".join(lines)

    def _parse_actions(self, raw: str, skill_name: str) -> list[OptimizeAction]:
        """解析 LLM 返回的 JSON"""
        try:
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not json_match:
                print(f"  [SkillOptimizer] 无法提取 JSON，原始输出：{raw[:200]}")
                self.last_analysis = ""
                return []

            data = json.loads(json_match.group())
            self.last_analysis = data.get("analysis", "")

            actions = []
            for a in data.get("actions", []):
                if a.get("action") == "patch":
                    actions.append(OptimizeAction(
                        action="patch",
                        skill_name=a.get("skill_name", skill_name),
                        reason=a.get("reason", ""),
                        old_text=a.get("old_text", ""),
                        new_text=a.get("new_text", ""),
                    ))
                elif a.get("action") == "create":
                    actions.append(OptimizeAction(
                        action="create",
                        skill_name=a.get("skill_name", ""),
                        reason=a.get("reason", ""),
                        content=a.get("content", ""),
                    ))

            print(f"  [SkillOptimizer] 生成了 {len(actions)} 个操作：{self.last_analysis[:80]}")
            return actions

        except json.JSONDecodeError as e:
            print(f"  [SkillOptimizer] JSON 解析失败: {e}\n原始: {raw[:300]}")
            self.last_analysis = ""
            return []

    def apply_actions(self, actions: list[OptimizeAction]) -> dict:
        """
        执行优化操作，返回执行结果统计。
        """
        results = {"patched": 0, "created": 0, "failed": 0, "details": []}

        for action in actions:
            try:
                if action.action == "patch":
                    success = self.skill_manager.patch(
                        skill_name=action.skill_name,
                        old_text=action.old_text,
                        new_text=action.new_text,
                        reason=action.reason,
                    )
                    if success:
                        results["patched"] += 1
                        results["details"].append(f"patch: {action.skill_name}")
                    else:
                        results["failed"] += 1
                        results["details"].append(f"patch FAILED: {action.skill_name}")

                elif action.action == "create":
                    success = self.skill_manager.create(
                        skill_name=action.skill_name,
                        content=action.content,
                        reason=action.reason,
                    )
                    if success:
                        results["created"] += 1
                        results["details"].append(f"create: {action.skill_name}")
                    else:
                        results["failed"] += 1
                        results["details"].append(f"create FAILED (exists?): {action.skill_name}")

            except Exception as e:
                results["failed"] += 1
                results["details"].append(f"ERROR: {action.skill_name} - {e}")

        return results


class RuleBasedOptimizer:
    """
    规则驱动的 Skill 优化器（无需 LLM）。

    当反馈模式明确且 Skill 修改简单时，可以用规则直接生成优化操作。
    适合处理高频、模式固定的反馈（如"缺少使用场景"→直接加一行规则）。

    使用方式：
        optimizer = RuleBasedOptimizer()
        actions = optimizer.generate_from_patterns(patterns)
    """

    # 反馈类别到 Skill 修改的映射规则
    RULE_MAPPINGS = {
        "缺少使用场景": {
            "patch_template": {
                "section": "内容要求",
                "old_keyword": "## 内容要求",
                "new_text": "## 内容要求\n- 必须包含使用场景/例句",
            }
        },
        "缺少对比": {
            "patch_template": {
                "section": "内容要求",
                "old_keyword": "## 内容要求",
                "new_text": "## 内容要求\n- 包含对比维度（如英式vs美式、正误对比等）",
            }
        },
        "缺少语法说明": {
            "patch_template": {
                "section": "内容要求",
                "old_keyword": "## 内容要求",
                "new_text": "## 内容要求\n- 必须包含语法/词法说明",
            }
        },
        "格式不清晰": {
            "patch_template": {
                "section": "输出格式",
                "old_keyword": "## 输出格式",
                "new_text": "## 输出格式\n- 使用清晰的层级结构，避免冗余",
            }
        },
    }

    def generate_from_patterns(
        self,
        patterns: list,
        skill_content: str,
    ) -> list[OptimizeAction]:
        """基于规则从模式生成优化操作"""
        actions = []

        for pattern in patterns[:2]:  # 最多处理2个模式
            rule = self.RULE_MAPPINGS.get(pattern.category)
            if not rule:
                continue

            template = rule.get("patch_template", {})
            old_keyword = template.get("old_keyword", "")
            new_text = template.get("new_text", "")

            if old_keyword in skill_content:
                actions.append(OptimizeAction(
                    action="patch",
                    skill_name="",  # 由调用方填充
                    reason=f"修复 {pattern.category}（{pattern.count} 条反馈）",
                    old_text=old_keyword,
                    new_text=new_text,
                ))

        return actions


# =============================================================================
# 开发者优化器：从执行效率、Token 消耗等角度优化 Skill
# =============================================================================

DEVELOPER_OPTIMIZER_SYSTEM = """你是 Skill 效率优化专家。你的任务是从**开发者视角**分析并优化 Skill，重点关注：

1. **执行效率**：Skill 是否过于复杂导致响应慢？
2. **Token 消耗**：Skill 内容是否冗余导致每次调用消耗过多 token？
3. **规则冗余**：是否有重复的规则或描述可以合并？
4. **分支过度**：条件分支是否过多导致模型需要多次判断？
5. **优先级不清**：规则之间是否有优先级冲突？

## 分析维度

### Token 消耗分析
- Skill 文件总 token 数（按 4 字符 ≈ 1 token 估算）
- 每次调用时 Skill 被加载的 token 开销
- 是否有过多的示例/注释可以压缩？

### 复杂度分析
- 条件分支数量（if/else 链）
- 正则表达式复杂度
- 嵌套层级深度

### 冗余分析
- 重复的描述段落
- 可以合并的相似规则
- 过长的示例列表

## 优化策略

1. **精简原则**：删除冗余描述，保留核心规则
2. **合并原则**：将相似规则合并，减少分支
3. **压缩原则**：用更简洁的表达替换冗长段落
4. **结构优化**：调整规则顺序，让常用规则在前

## Skill 结构参考

Skill 文件格式：
```markdown
---
name: xxx
description: 简短描述
version: X
---

# 标题

内容正文，包含：
- 规则列表
- 条件分支
- 示例
- 注释
```

## 输出格式

只输出 JSON，不要有其他文字：
{{
  "analysis": {{
    "token_count": 估算的 token 数,
    "rule_count": 规则数量,
    "branch_count": 条件分支数量,
    "issues": ["问题1", "问题2"],
    "efficiency_score": "高/中/低"
  }},
  "actions": [
    {{
      "action": "patch",
      "skill_name": "xxx",
      "reason": "优化原因",
      "old_text": "精确的原始文本",
      "new_text": "优化后的文本"
    }}
  ]
}}

如果没有需要优化的地方，actions 可以为空数组。"""


DEVELOPER_OPTIMIZER_USER = """## 当前 Skill 内容

```markdown
{skill_content}
```

## 调用统计（如果有）

```json
{usage_stats}
```

请分析这个 Skill 的执行效率和 token 消耗，给出优化建议。"""


class DeveloperOptimizer:
    """
    开发者视角的 Skill 优化器。

    从以下角度分析并优化 Skill：
    1. Token 消耗：Skill 太大导致每次调用成本高
    2. 执行效率：规则太复杂导致响应慢
    3. 冗余内容：重复的描述、过多的示例
    4. 结构优化：规则顺序、优先级调整

    使用方式：
        optimizer = DeveloperOptimizer(skill_manager)
        result = optimizer.analyze_and_optimize("flashcard", usage_stats={"calls": 100, "avg_token": 5000})
    """

    def __init__(
        self,
        skill_manager: SkillManager,
        model: str = "deepseek-chat",
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
    ):
        self.skill_manager = skill_manager
        self.model = model
        if api_key:
            os.environ["DEEPSEEK_API_KEY"] = api_key
        from openai import OpenAI
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY", api_key or ""),
            base_url=base_url,
        )

    def estimate_token_count(self, text: str) -> int:
        """估算 token 数（按 4 字符 ≈ 1 token）"""
        return len(text) // 4

    def analyze_skill(self, skill_name: str) -> dict:
        """
        分析单个 Skill 的效率和消耗指标。
        """
        content = self.skill_manager.get(skill_name)
        if not content:
            return {"error": f"Skill '{skill_name}' not found"}

        # 基础指标
        token_count = self.estimate_token_count(content)
        char_count = len(content)

        # 规则数量（# 开头的标题）
        import re
        rules = re.findall(r'^##?\s+.+$', content, re.MULTILINE)
        rule_count = len(rules)

        # 条件分支（包含 if/when/case 的行）
        branches = re.findall(r'(?i)(if|when|case|otherwise|default)', content)
        branch_count = len(branches)

        # 列表项数量（- 或 * 开头的行）
        list_items = re.findall(r'^[-*]\s+.+$', content, re.MULTILINE)
        list_count = len(list_items)

        # 代码块数量（``` 开头的）
        code_blocks = re.findall(r'```', content)
        code_block_count = len(code_blocks) // 2

        # 估算效率分数
        efficiency_score = self._calculate_efficiency_score(
            token_count=token_count,
            rule_count=rule_count,
            branch_count=branch_count,
            list_count=list_count,
        )

        # 识别问题
        issues = []
        if token_count > 3000:
            issues.append(f"Skill 较大（≈{token_count} tokens），考虑精简")
        if branch_count > 15:
            issues.append(f"条件分支较多（{branch_count}），考虑合并")
        if list_count > 30:
            issues.append(f"列表项过多（{list_count}），考虑压缩示例")
        if code_block_count > 5:
            issues.append(f"代码块较多（{code_block_count}），考虑精简示例")

        return {
            "skill_name": skill_name,
            "metrics": {
                "token_count": token_count,
                "char_count": char_count,
                "rule_count": rule_count,
                "branch_count": branch_count,
                "list_count": list_count,
                "code_block_count": code_block_count,
            },
            "efficiency_score": efficiency_score,
            "issues": issues,
        }

    def _calculate_efficiency_score(
        self,
        token_count: int,
        rule_count: int,
        branch_count: int,
        list_count: int,
    ) -> str:
        """计算效率分数：高/中/低"""
        score = 100

        # Token 消耗扣分
        if token_count > 4000:
            score -= 40
        elif token_count > 2500:
            score -= 20
        elif token_count > 1500:
            score -= 10

        # 分支复杂度扣分
        if branch_count > 20:
            score -= 30
        elif branch_count > 10:
            score -= 15
        elif branch_count > 5:
            score -= 5

        # 列表项过多扣分
        if list_count > 50:
            score -= 20
        elif list_count > 30:
            score -= 10

        if score >= 70:
            return "高"
        elif score >= 40:
            return "中"
        return "低"

    def analyze_and_optimize(
        self,
        skill_name: str,
        usage_stats: Optional[dict] = None,
        auto_apply: bool = False,
    ) -> dict:
        """
        分析并优化指定 Skill。

        Args:
            skill_name: 要优化的 Skill 名称
            usage_stats: 可选的调用统计 {"calls": N, "avg_token": T, "avg_time": S}
            auto_apply: 是否自动应用优化建议

        Returns:
            包含分析结果和优化操作的结果
        """
        # 1. 获取 Skill 内容
        content = self.skill_manager.get(skill_name)
        if not content:
            return {"error": f"Skill '{skill_name}' not found"}

        # 2. 本地分析
        local_analysis = self.analyze_skill(skill_name)

        # 3. 如果问题不多，用规则优化
        if len(local_analysis["issues"]) <= 1:
            actions = self._generate_rule_based_optimization(content, local_analysis)
            if not actions:
                return {
                    "status": "no_optimization_needed",
                    "analysis": local_analysis,
                    "actions": [],
                }

            if auto_apply:
                return self._apply_actions(actions, skill_name)
            return {
                "status": "rule_based",
                "analysis": local_analysis,
                "actions": [a.to_dict() for a in actions],
            }

        # 4. 问题较多，用 LLM 分析
        usage_stats_text = json.dumps(usage_stats, ensure_ascii=False) if usage_stats else "（无统计）"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": DEVELOPER_OPTIMIZER_SYSTEM},
                {"role": "user", "content": DEVELOPER_OPTIMIZER_USER.format(
                    skill_content=content,
                    usage_stats=usage_stats_text,
                )},
            ],
            temperature=0,
            max_tokens=3000,
        )

        raw = response.choices[0].message.content.strip()
        return self._parse_llm_response(raw, skill_name, local_analysis, auto_apply)

    def _generate_rule_based_optimization(self, content: str, analysis: dict) -> list[OptimizeAction]:
        """基于规则生成优化操作（无需 LLM）"""
        actions = []
        metrics = analysis.get("metrics", {})

        # 问题1：示例过多，压缩列表项
        if metrics.get("list_count", 0) > 30:
            # 找到最长的列表块，尝试压缩
            import re
            lines = content.split("\n")
            in_list = False
            list_lines = []
            list_start = -1

            for i, line in enumerate(lines):
                if re.match(r'^[-*]\s+', line):
                    if not in_list:
                        in_list = True
                        list_start = i
                    list_lines.append(line)
                else:
                    if in_list and len(list_lines) > 10:
                        # 保留前5个和后3个，中间压缩
                        keep_count = min(5, len(list_lines))
                        old_text = "\n".join(list_lines[:keep_count] + ["..."] + list_lines[-3:])
                        new_text = "\n".join(list_lines[:5] + ["..."] + list_lines[-3:])
                        if old_text in content:
                            actions.append(OptimizeAction(
                                action="patch",
                                skill_name="",
                                reason=f"压缩示例列表（{len(list_lines)} → 8 条）",
                                old_text=old_text,
                                new_text=new_text,
                            ))
                            break
                    in_list = False
                    list_lines = []

        # 问题2：多个连续空行压缩
        if "\n\n\n" in content:
            old_text = "\n\n\n"
            new_text = "\n\n"
            actions.append(OptimizeAction(
                action="patch",
                skill_name="",
                reason="删除多余空行",
                old_text=old_text,
                new_text=new_text,
            ))

        return actions

    def _parse_llm_response(
        self,
        raw: str,
        skill_name: str,
        local_analysis: dict,
        auto_apply: bool,
    ) -> dict:
        """解析 LLM 返回的优化建议"""
        try:
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not json_match:
                return {
                    "status": "parse_error",
                    "raw": raw[:200],
                    "analysis": local_analysis,
                }

            data = json.loads(json_match.group())
            analysis = data.get("analysis", local_analysis)

            actions = []
            for a in data.get("actions", []):
                if a.get("action") == "patch":
                    actions.append(OptimizeAction(
                        action="patch",
                        skill_name=a.get("skill_name", skill_name),
                        reason=a.get("reason", ""),
                        old_text=a.get("old_text", ""),
                        new_text=a.get("new_text", ""),
                    ))

            if not actions:
                return {
                    "status": "no_actions",
                    "analysis": analysis,
                    "actions": [],
                }

            if auto_apply:
                return self._apply_actions(actions, skill_name)

            return {
                "status": "llm_based",
                "analysis": analysis,
                "actions": [a.to_dict() for a in actions],
            }

        except json.JSONDecodeError:
            return {
                "status": "parse_error",
                "raw": raw[:200],
                "analysis": local_analysis,
            }

    def _apply_actions(self, actions: list[OptimizeAction], skill_name: str) -> dict:
        """应用优化操作"""
        results = {"patched": 0, "failed": 0, "details": []}
        for action in actions:
            action.skill_name = skill_name
            success = self.skill_manager.patch(
                skill_name=action.skill_name,
                old_text=action.old_text,
                new_text=action.new_text,
                reason=f"[DeveloperOptimizer] {action.reason}",
            )
            if success:
                results["patched"] += 1
                results["details"].append(f"patched: {action.reason[:50]}")
            else:
                results["failed"] += 1
                results["details"].append(f"failed: {action.reason[:50]}")
        return {
            "status": "applied",
            "results": results,
            "actions": [a.to_dict() for a in actions],
        }

    def analyze_all_skills(self) -> dict[str, dict]:
        """分析所有 Skill 的效率"""
        results = {}
        for skill_name in self.skill_manager.load_all().keys():
            results[skill_name] = self.analyze_skill(skill_name)
        return results
