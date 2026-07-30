"""
通用数据分析脚本 (demo)

教学用途：演示 Skill 引用脚本时的渐进式 Level 2 加载
——LLM 先 load_skill("data-analysis") 看到 SKILL.md 引用了此脚本，
   再调用 read_file 读取此脚本了解功能，
   最后 run_command 执行分析。

用法：
  python analyze.py <csv_file>            # 分析 CSV 文件概要
  python analyze.py <csv_file> --column   # 逐列统计
  python analyze.py <csv_file> --top N    # 显示前 N 行

示例：
  python analyze.py data/sample.csv
  python analyze.py data/sample.csv --column
"""

import sys
import csv
import json
from pathlib import Path
from collections import Counter


def analyze_csv(filepath: str, mode: str = "summary", top_n: int = 5):
    """分析 CSV 文件"""
    path = Path(filepath)
    if not path.exists():
        print(f"[错误] 文件不存在：{filepath}")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        columns = reader.fieldnames or []

    total = len(rows)
    print(f"\n=== 数据分析报告：{path.name} ===")
    print(f"文件大小：{path.stat().st_size:,} 字节")
    print(f"总行数：{total:,}")
    print(f"总列数：{len(columns)}")
    print(f"列名：{', '.join(columns)}")

    if mode == "summary" or mode == "top":
        print(f"\n--- 前 {top_n} 行预览 ---")
        for i, row in enumerate(rows[:top_n]):
            print(f"  [{i+1}] {json.dumps(row, ensure_ascii=False)}")

    if mode == "column":
        print("\n--- 逐列统计 ---")
        for col in columns:
            values = [r.get(col, "") for r in rows]
            non_empty = [v for v in values if v.strip()]
            print(f"\n  [{col}]")
            print(f"    非空：{len(non_empty)}/{len(values)} ({100*len(non_empty)/len(values):.1f}%)")
            if non_empty:
                # 尝试数值统计
                try:
                    nums = [float(v) for v in non_empty]
                    print(f"    最小值：{min(nums):.2f}  最大值：{max(nums):.2f}")
                    print(f"    平均值：{sum(nums)/len(nums):.2f}")
                except ValueError:
                    # 文本列：显示最常见值
                    top_vals = Counter(non_empty).most_common(3)
                    vals_str = ", ".join(f'"{v}"(×{c})' for v, c in top_vals)
                    print(f"    最常见：{vals_str}")

    print("\n=== 报告结束 ===\n")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return

    filepath = sys.argv[1]
    mode = "summary"

    for arg in sys.argv[2:]:
        if arg == "--column":
            mode = "column"
        elif arg == "--top" and len(sys.argv) > sys.argv.index(arg) + 1:
            try:
                top_n = int(sys.argv[sys.argv.index(arg) + 1])
                mode = "top"
            except (ValueError, IndexError):
                pass

    analyze_csv(filepath, mode)


if __name__ == "__main__":
    main()
