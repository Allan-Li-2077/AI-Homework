# 作业说明：省份人口柱状图 Skill

## 一、作业目标

在 Agent 记忆系统中实现一个**可执行 Skill**：当用户输入省份名称时，系统自动完成以下三步：

1. **查找**该省份各地州市（或直辖市各区）的人口总量  
2. **绘制**各地市人口柱状图（单位：万人，柱体颜色不同，尽量美观）  
3. **写出** HTML 文件，文件名为 `{省份名称}.html`

通过本作业，理解 Cursor 风格 Agent Skill 的三个要点：

- Skill 说明书（`SKILL.md`）如何描述「何时用、怎么做」  
- 渐进披露：目录注入 description，命中后再加载全文  
- **可执行脚本**：Skill 不只是提示词，还能真正跑代码、落盘文件  

---

## 二、交付物结构

请保证仓库中存在如下目录（名称需一致）：

```text
skills/province-population-chart/
├── SKILL.md                          # Skill 说明书（YAML frontmatter + 正文）
├── data.json                         # 各省地市人口数据（单位：万人）
└── scripts/
    └── generate_chart.py             # 生成柱状图 HTML 的脚本
```

可选配套（若课程要求接入对话系统）：

```text
src/skill_loader.py                   # Skill 扫描 / 匹配 / 注入
src/skill_executor.py                 # 检测到省名后调用脚本
outputs/charts/{省份}.html            # 运行时生成的图表文件
```

---

## 三、功能要求（评分要点）

### 3.1 触发方式

至少支持以下之一（推荐全部支持）：

| 触发 | 示例 |
|------|------|
| 直接输入省名 | `广东`、`浙江省` |
| 自然语言 | `生成四川各地市人口柱状图` |
| 显式调用 | `/skill province-population-chart` 或 `@province-population-chart` |

### 3.2 数据与查询

- 使用本地 `data.json`（可基于第七次全国人口普查常住人口，数值以**万人**为单位，允许约数）  
- 支持常见写法归一化：`广东` / `广东省` 指向同一条数据  
- 省份不存在时，给出清晰错误提示，并尽量列出已支持省份  

### 3.3 柱状图与 HTML

- 每个地市一根柱，**颜色互不相同**（可循环调色板）  
- 单位明确标注为**万人**  
- 建议按人口**降序**排列，并显示数值标签  
- 纯 HTML（可用内联 SVG/CSS），**不依赖外网 CDN** 为佳  
- 输出文件名：`{省份}.html`（例如 `广东.html`）  
- 推荐输出目录：`outputs/charts/`  

### 3.4 Skill 说明书（SKILL.md）

frontmatter 至少包含：

```yaml
---
name: province-population-chart
description: >-
  Looks up prefecture-level city populations for a Chinese province, renders a
  colorful bar chart (unit: 万人), and writes an HTML file named {省份}.html.
  Use when the user inputs a province name such as 广东、浙江省、四川, or asks for
  人口柱状图、各地市人口、省份人口统计图.
---
```

正文需写清：

- 使用场景（When to use）  
- 必须执行的命令（Execute）  
- 回复规范（告知路径与人口要点，**不要**在聊天里粘贴整段 HTML）  

---

## 四、推荐实现步骤

1. **准备数据**  
   编写 `data.json`，结构示例：

   ```json
   {
     "广东": { "广州": 1868, "深圳": 1756, "东莞": 1047 },
     "浙江": { "杭州": 1194, "宁波": 940 }
   }
   ```

2. **实现生成脚本**  

   ```bash
   python skills/province-population-chart/scripts/generate_chart.py 广东
   ```

   成功时在标准输出打印生成文件的路径。

3. **编写 SKILL.md**  
   按第三节要求写清触发词、工作流与约束。

4. **（进阶）接入对话流水线**  
   - 用 `skill_loader` 匹配并注入 Skill  
   - 用 `skill_executor` 在识别到省名时 `subprocess` 调用脚本  
   - 通过 SSE 事件（如 `skill_exec`）把执行结果推到前端  

5. **自测**  
   - 生成至少 2 个省份的 HTML，用浏览器打开检查样式与数据  
   - 测错误输入（不支持的省份名）  

---

## 五、验收标准

| 序号 | 检查项 | 通过标准 |
|------|--------|----------|
| 1 | 目录与命名 | 存在 `skills/province-population-chart/` 且含 `SKILL.md`、`data.json`、脚本 |
| 2 | 命令行可跑 | `generate_chart.py <省名>` 能生成 HTML |
| 3 | 文件命名 | 输出为 `{省份}.html` |
| 4 | 图表质量 | 多色柱状图、单位万人、城市名与数值可读 |
| 5 | Skill 描述 | `description` 含「做什么 + 何时用」及触发关键词 |
| 6 | 对话集成（若要求） | 输入省名可自动生成，并返回文件路径说明 |

---

## 六、提交说明

请提交：

1. 完整 `skills/province-population-chart/` 目录  
2. 至少 2 个样例 HTML（如 `outputs/charts/广东.html`、`outputs/charts/浙江.html`）  
3. （可选）一段简短说明：你如何触发 Skill、踩过什么坑（编码、路径、中文文件名等）  

**截止与提交方式**：按课程老师要求（仓库 PR / 压缩包 / 学习平台）。

---

## 七、参考命令速查

```bash
# 安装依赖（若尚未安装项目依赖）
pip install -r requirements.txt

# 单独生成某省图表
python skills/province-population-chart/scripts/generate_chart.py 广东

# 启动 Web 演示（若已接入 serve.py）
uvicorn src.serve:app --host 0.0.0.0 --port 8003
# 浏览器打开 http://localhost:8003 ，输入「广东」
```

---

## 八、扩展思考（加分项）

- 支持更多省份或把数据升级为「万人保留一位小数」  
- 增加横向柱状图 / 排序切换（升序/降序）  
- Web 端提供「打开图表」链接（如 `/charts/广东.html`）  
- 将人口数据来源与更新日期写进 HTML 页脚  
- 对比：只用 Prompt 让模型「假装生成」vs 真正执行脚本落盘，各有什么风险？  
