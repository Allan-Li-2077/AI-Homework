#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
skill_optimize 模块测试脚本

运行方式（在项目根目录）:
    python -c "from skill_optimize.test_skill_optimize import main; main()"

依赖:
    - openai (用于 LLM 相关功能)
    - skill_manager (在 src/ 目录)
"""

import sys
import os

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

# 设置 UTF-8 输出
os.environ['PYTHONIOENCODING'] = 'utf-8'
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def test_skill_manager():
    """测试 SkillManager"""
    from skill_manager import SkillManager
    sm = SkillManager('skills-origin')
    skills = sm.load_all()
    print(f"[PASS] SkillManager: loaded {len(skills)} skills: {list(skills.keys())}")
    return sm


def test_feedback_collector():
    """测试 UserFeedbackCollector"""
    from user_feedback_collector import UserFeedbackCollector

    # 使用默认路径（skill_optimize/outputs/user_feedback）
    collector = UserFeedbackCollector()

    # 记录显式反馈
    fb1 = collector.record(
        skill_name='flash-card',
        user_input='apple',
        generated_output="['apple', '苹果']",
        feedback_text='缺少使用场景举例，能造个句子吗？',
    )
    assert fb1.feedback_type == 'suggestion'

    # 记录追问反馈
    fb2 = collector.record_from_follow_up(
        skill_name='flash-card',
        user_input='apple',
        generated_output="['apple', '苹果']",
        follow_up_text='能不能加上英式和美式发音的对比？',
    )
    assert fb2.feedback_type == 'suggestion'

    # 记录隐式反馈
    fb3 = collector.record_from_implicit(
        skill_name='flash-card',
        user_input='apple',
        original_output="['apple']",
        revised_output="['apple', '英:/ˈæpəl/', '美:/ˈæpəl/']",
    )
    assert fb3.feedback_type == 'complaint'

    # 写入磁盘
    collector.flush_to_disk()
    print(f"       (feedbacks flushed to: {collector.storage_dir})")

    print(f"[PASS] UserFeedbackCollector: recorded 3 feedbacks")
    return collector


def test_feedback_analyzer():
    """测试 FeedbackAnalyzer"""
    from feedback_analyzer import FeedbackAnalyzer

    analyzer = FeedbackAnalyzer()

    # 模拟反馈列表
    class MockFeedback:
        def __init__(self, text, ftype='suggestion'):
            self.feedback_text = text
            self.feedback_type = ftype
            self.user_input = ''
            self.timestamp = ''

        def to_dict(self):
            return {'feedback_text': self.feedback_text, 'feedback_type': self.feedback_type}

    feedbacks = [
        MockFeedback('缺少使用场景举例，能造个句子吗？'),
        MockFeedback('建议加上英式和美式发音的对比'),
        MockFeedback('格式有点乱，看不懂'),
        MockFeedback('缺少语法说明'),
        MockFeedback('很好，满意'),
    ]

    patterns = analyzer.analyze(feedbacks)
    print(f"[PASS] FeedbackAnalyzer: found {len(patterns)} patterns")
    for p in patterns:
        print(f"       - {p.category}: {p.count}次")

    return patterns


def test_rule_based_optimizer():
    """测试 RuleBasedOptimizer"""
    from skill_optimizer import RuleBasedOptimizer

    optimizer = RuleBasedOptimizer()

    class MockPattern:
        def __init__(self, category, count):
            self.category = category
            self.count = count

    patterns = [
        MockPattern('缺少使用场景', 5),
        MockPattern('缺少对比', 3),
    ]

    skill_content = """## 内容要求
- 必须包含词性和音标
- 示例数量 3-5 个
"""

    actions = optimizer.generate_from_patterns(patterns, skill_content)
    print(f"[PASS] RuleBasedOptimizer: generated {len(actions)} actions")

    return actions


def test_developer_optimizer(sm):
    """测试 DeveloperOptimizer"""
    from skill_optimizer import DeveloperOptimizer

    dev_opt = DeveloperOptimizer(sm)

    # 分析 baoyu-diagram
    analysis = dev_opt.analyze_skill('baoyu-diagram')
    print(f"[PASS] DeveloperOptimizer.analyze_skill:")
    print(f"       skill: {analysis['skill_name']}")
    print(f"       token_count: {analysis['metrics']['token_count']}")
    print(f"       efficiency_score: {analysis['efficiency_score']}")

    return analysis


def test_online_optimization():
    """测试在线优化（用户反馈后立即处理）"""
    from skill_optimize import SkillOptimizeManager

    manager = SkillOptimizeManager(skills_dir='skills-origin')

    # 测试规则模式
    print("\n--- 测试规则模式在线优化 ---")
    result = manager.process_feedback_now(
        skill_name='flash-card',
        user_input='apple',
        generated_output="['apple', '苹果']",
        feedback_text='缺少使用场景举例，能造个句子吗？',
        use_llm=False,
    )
    print(f"     规则模式 status: {result['status']}")

    # 测试 LLM 模式
    print("\n--- 测试 LLM 模式在线优化 ---")
    manager.set_llm_optimizer()  # 从环境变量读取
    result = manager.process_feedback_now(
        skill_name='flash-card',
        user_input='banana',
        generated_output="['banana', '香蕉']",
        feedback_text='建议加上英式和美式发音的对比',
        use_llm=True,
    )
    print(f"     LLM模式 status: {result['status']}")
    if result.get('status') == 'updated':
        print(f"     reason: {result.get('reason', '')[:60]}")


def main():
    print("=" * 60)
    print("skill_optimize 模块测试")
    print("=" * 60)

    try:
        print("\n1. 测试 SkillManager...")
        sm = test_skill_manager()

        print("\n2. 测试 UserFeedbackCollector...")
        test_feedback_collector()

        print("\n3. 测试 FeedbackAnalyzer...")
        test_feedback_analyzer()

        print("\n4. 测试 RuleBasedOptimizer...")
        test_rule_based_optimizer()

        print("\n5. 测试 DeveloperOptimizer...")
        test_developer_optimizer(sm)

        print("\n6. 测试在线优化...")
        test_online_optimization()

        print("\n" + "=" * 60)
        print("所有测试通过!")
        print("=" * 60)

    except Exception as e:
        print(f"\n[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
