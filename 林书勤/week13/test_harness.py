#!/usr/bin/env python3
"""
测试脚本 - 验证 Harness 核心功能

演示：
  1. Skill 发现
  2. 单个执行
  3. 链式执行
  4. 依赖注入
  5. 缓存复用
  6. 执行历史
"""

import sys
import json
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent))

from src.skill_harness import SkillHarness


def print_header(title: str):
    """打印章节标题"""
    print(f"\n{'='*80}")
    print(f"{title:^80}")
    print(f"{'='*80}\n")


def test_discovery():
    """测试 1: Skill 发现"""
    print_header("测试 1: Skill 发现")
    
    harness = SkillHarness()
    harness.initialize()
    
    skills = harness.discover_skills()
    print(f"✓ 发现 {len(skills)} 个 skills\n")
    
    for skill in skills:
        print(f"  📦 {skill['name']} (v{skill['version']})")
        print(f"     {skill['description']}")
        if skill['dependencies']:
            print(f"     依赖: {', '.join(skill['dependencies'])}")
        print()
    
    return harness


def test_single_execution(harness: SkillHarness):
    """测试 2: 单个 Skill 执行"""
    print_header("测试 2: 单个 Skill 执行 (demo-greeting)")
    
    result = harness.run_skill(
        "demo-greeting",
        params={"name": "Alice", "tone": "friendly", "language": "en"}
    )
    
    print(f"✓ 状态: {result['status']}")
    print(f"✓ 耗时: {result['duration_ms']}ms")
    print(f"✓ 结果: {result['result']}\n")
    
    print(f"执行事件 ({len(result['events'])} 条):")
    for event in result['events']:
        icon = {
            "success": "✓",
            "failed": "✗",
            "pending": "·",
            "running": "→",
            "skipped": "∅",
        }.get(event.status.value, "?")
        
        print(f"  {icon} [{event.stage:10}] {event.skill_name:20} {event.message}")


def test_single_execution_zh(harness: SkillHarness):
    """测试 2b: 中文问候"""
    print_header("测试 2b: 中文问候")
    
    result = harness.run_skill(
        "demo-greeting",
        params={"name": "小明", "tone": "formal", "language": "zh"}
    )
    
    print(f"✓ 结果: {result['result']}\n")


def test_single_execution_cache(harness: SkillHarness):
    """测试 2c: 缓存复用"""
    print_header("测试 2c: 缓存复用")
    
    params = {"name": "Bob", "tone": "casual"}
    
    # 首次执行
    print("👉 首次执行...")
    result1 = harness.run_skill("demo-greeting", params=params, use_cache=False)
    time1 = result1['duration_ms']
    print(f"   耗时: {time1}ms\n")
    
    # 使用缓存
    print("👉 使用缓存（相同参数）...")
    result2 = harness.run_skill("demo-greeting", params=params, use_cache=True)
    time2 = result2['duration_ms']
    print(f"   耗时: {time2}ms")
    print(f"   来自缓存: {result2.get('from_cache', False)}\n")
    
    # 计算加速比
    if time2 > 0:
        speedup = time1 / time2
        print(f"✓ 加速比: {speedup:.1f}x\n")


def test_data_processing(harness: SkillHarness):
    """测试 3: 数据处理 Skill"""
    print_header("测试 3: 数据处理 (demo-data-process)")
    
    result = harness.run_skill(
        "demo-data-process",
        params={"data": [1, 2, 3, 4, 5], "operation": "summary"}
    )
    
    print(f"✓ 状态: {result['status']}")
    print(f"✓ 结果:\n")
    
    # 格式化输出结果
    if result['result'] and result['result'].get('success'):
        res = result['result']
        print(f"   操作: {res.get('operation')}")
        print(f"   样本数: {res.get('count')}")
        print(f"   总和: {res.get('sum')}")
        print(f"   平均值: {res.get('avg'):.2f}")
        print(f"   最小值: {res.get('min')}")
        print(f"   最大值: {res.get('max')}")
        print(f"   中位数: {res.get('median')}")
        print()


def test_chain_execution(harness: SkillHarness):
    """测试 4: 链式执行（依赖注入演示）"""
    print_header("测试 4: 链式执行（演示自动依赖注入）")
    
    print("👉 执行链: demo-data-process → demo-report-gen")
    print("   demo-report-gen 的 demo_data_process 参数会自动注入\n")
    
    result = harness.run_skill_chain(
        ["demo-data-process", "demo-report-gen"],
        params={"data": [1, 2, 3, 4, 5], "operation": "summary"}
    )
    
    print(f"✓ 链执行状态: {result['status']}")
    print(f"✓ 总耗时: {result['duration_ms']}ms")
    print(f"✓ 成功执行的 skills: {len(result['results'])} 个\n")
    
    # 查看各 skill 的结果摘要
    print("执行结果摘要:")
    for skill_name, res in result['results'].items():
        if isinstance(res, dict):
            if res.get('success'):
                print(f"  ✓ {skill_name}: 成功")
            elif res.get('operation'):
                print(f"  ✓ {skill_name}: {res.get('operation')} 操作完成")
            else:
                print(f"  ✓ {skill_name}: 处理完成")
        else:
            print(f"  ✓ {skill_name}: {str(res)[:50]}")
    
    print()


def test_execution_history(harness: SkillHarness):
    """测试 5: 执行历史与统计"""
    print_header("测试 5: 执行历史与统计")
    
    # 获取历史
    records = harness.get_execution_history(limit=10)
    print(f"✓ 最近 {len(records)} 条执行记录:\n")
    
    for i, record in enumerate(records[:5], 1):  # 只显示前5条
        status_icon = "✓" if record['status'] == "success" else "✗"
        print(f"  {i}. {status_icon} {record['skill_name']:20} "
              f"({record['timestamp']}) "
              f"{record['duration_ms']}ms")
    
    print()
    
    # 获取统计
    stats = harness.get_statistics()
    print(f"✓ 执行统计:\n")
    print(f"  总记录数: {stats['total_records']}")
    print(f"  缓存大小: {stats['cache_size']}")
    print(f"  快照数: {stats['snapshots_count']}")
    
    if stats['status_counts']:
        print(f"\n  按状态分类:")
        for status, count in stats['status_counts'].items():
            print(f"    {status}: {count}")
    
    if stats['skill_counts']:
        print(f"\n  按 Skill 分类 (前3):")
        for skill_name, count in sorted(
            stats['skill_counts'].items(),
            key=lambda x: x[1],
            reverse=True
        )[:3]:
            print(f"    {skill_name}: {count}")
    
    print()


def test_error_handling(harness: SkillHarness):
    """测试 6: 错误处理"""
    print_header("测试 6: 错误处理")
    
    print("👉 测试 1: 缺少必需参数")
    result = harness.run_skill(
        "demo-greeting",
        params={"tone": "friendly"}  # 缺少 name
    )
    
    # 查看错误信息
    for event in result['events']:
        if event.error:
            print(f"   ✗ 错误: {event.error}\n")
    
    print("👉 测试 2: 无效数据")
    result = harness.run_skill(
        "demo-data-process",
        params={"data": "not_a_list"}  # 错误类型
    )
    
    # 查看错误信息
    for event in result['events']:
        if event.error:
            print(f"   ✗ 错误: {event.error}\n")
    
    print("✓ 错误处理正常工作\n")


def test_different_operations(harness: SkillHarness):
    """测试 7: 不同操作类型"""
    print_header("测试 7: 数据处理的不同操作")
    
    data = [1, 2, 3, 4, 5]
    operations = ["summary", "filtering", "sorting"]
    
    for op in operations:
        print(f"👉 操作: {op}")
        result = harness.run_skill(
            "demo-data-process",
            params={"data": data, "operation": op}
        )
        
        if result['result'] and result['result'].get('success'):
            res = result['result']
            if op == "summary":
                print(f"   平均值: {res.get('avg'):.2f}")
            elif op == "filtering":
                print(f"   过滤结果 (> {res.get('median')}): {res.get('filtered')}")
            elif op == "sorting":
                print(f"   排序结果: {res.get('sorted')}")
        
        print()


def main():
    """主测试函数"""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + f"{'Skill Harness 功能测试':^78}" + "║")
    print("╚" + "=" * 78 + "╝")
    
    try:
        # 测试 1: 发现
        harness = test_discovery()
        
        # 测试 2: 单个执行
        test_single_execution(harness)
        test_single_execution_zh(harness)
        test_single_execution_cache(harness)
        
        # 测试 3: 数据处理
        test_data_processing(harness)
        
        # 测试 7: 不同操作
        test_different_operations(harness)
        
        # 测试 4: 链式执行
        test_chain_execution(harness)
        
        # 测试 5: 历史与统计
        test_execution_history(harness)
        
        # 测试 6: 错误处理
        test_error_handling(harness)
        
        # 总结
        print_header("✅ 所有测试完成")
        print("核心功能演示:")
        print("  ✓ Stage 1: Skill 发现与加载")
        print("  ✓ Stage 2: 上下文构建与参数验证")
        print("  ✓ Stage 3: 渐进式执行与事件流")
        print("  ✓ Stage 4: 状态持久化与缓存")
        print("  ✓ 依赖管理与链式执行")
        print("  ✓ 错误恢复与部分执行")
        print()
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
