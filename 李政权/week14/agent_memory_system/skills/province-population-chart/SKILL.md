---
name: province-population-chart
description: >-
  Looks up prefecture-level city populations for a Chinese province, renders a
  colorful bar chart (unit: 万人), and writes an HTML file named {省份}.html.
  Use when the user inputs a province name such as 广东、浙江省、四川, or asks for
  人口柱状图、各地市人口、省份人口统计图.
---

# Province Population Chart

## Goal
用户给出**省份名称**时，自动完成：
1. 查找该省各地市（或直辖市各区）人口总量
2. 生成彩色柱状图（单位：万人，柱体颜色不同）
3. 写入 HTML 文件，文件名为 `{省份}.html`

## When to use
- 用户只说了省名，如「广东」「浙江省」
- 用户说「生成广东各地市人口柱状图」
- 显式调用：`/skill province-population-chart` 或 `@province-population-chart`

## Execute（必须跑脚本，不要手写 HTML）

```bash
python skills/province-population-chart/scripts/generate_chart.py <省份名>
```

成功时 stdout 为生成文件的绝对/相对路径，默认输出到 `outputs/charts/{省份}.html`。

## Response rules
- 确认已生成的文件路径
- 用 3～6 条要点概括：地市数量、合计人口、人口最多的城市
- **不要**在聊天里粘贴整段 HTML
- 若省份不在数据中，说明已支持列表，请用户换一个省
- 数据来源说明：技能包内置第七次人口普查汇总（万人，约数）

## Data
人口数据见同目录 [data.json](data.json)。
