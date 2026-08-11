# USAGE_GUIDE.md — Progressive Skill Harness 使用指南

## 快速开始

### 1. 安装依赖
```powershell
.\setup_env.ps1
```
按提示输入 DeepSeek / DashScope API Key。

### 2. 启动服务

**Web 版（推荐）**：
```powershell
.\start.ps1 web
```
浏览器访问 http://localhost:8000

**CLI 版**：
```powershell
.\start.ps1 cli
```

### 3. 冒烟测试（不依赖 LLM）
```powershell
.\start.ps1 smoke
```

---

## 体验流程

### 第一次对话（直接回答）
输入：
> 你好

观察右侧面板：
- ✅ Layer 3 亮起（加载了 4 个 .md）
- ✅ S0 注册表亮起（启动时已完成）
- ✅ S1 决策：**direct_answer**（置信度 ~60%）
- ❌ S2/S3 未亮（没调用 skill）
- ❌ L4 可能命中历史

### 触发 Skill 的对话
输入：
> 帮我把"你好世界"翻译成英文

观察加载流程（每个 trace 事件都会显示在对话流中）：
1. **S0**：7 个 skill 已索引（5KB frontmatter）
2. **S1 决策**：translate skill（action=skill_call，置信度 ~95%）
3. **S2 加载**：读 translate/SKILL.md，1.5KB 正文，~2ms
4. **S3 执行**：prompt 型，调 LLM 流式生成（看到 token 逐个出现）
5. **L4 检索**：可能命中过往 skill 调用记录
6. **S4 写入**：MEMORY.md 追加一条 `[skill_call] 调用 skill: translate`

### 触发 code 型 skill
输入：
> 读取 requirements.txt 文件内容

观察：
1. **S1 决策**：file_reader（execution=code）
2. **S2 加载**：读 file_reader/SKILL.md + 不读 code.py（仅在执行时动态加载）
3. **S3 执行**：sandbox 运行 code.py，**不调 LLM**，直接读文件

### 触发 workflow 型 skill
输入：
> 研究一下 LLM Agent 的最新进展

观察：
1. **S1 决策**：research_workflow
2. **S2 加载**：research_workflow 的 SKILL.md
3. **S3 执行**：连续两次执行 —— 先 web_search，再 summarize

---

## 自定义 Skill

### 步骤 1：创建目录
```powershell
mkdir skills\my_skill
```

### 步骤 2：写 SKILL.md
```markdown
---
name: my_skill
version: 1.0.0
description: 一句话描述它能干什么（这是 LLM 决定要不要调用的关键）
keywords: [关键词1, 关键词2]
triggers: [trigger_name]
execution: prompt
parameters:
  - name: input
    type: string
    required: true
    description: 输入说明
---

# 我的 Skill

你是一个 ... 请基于以下输入 ...

输入：`{{input}}`

## 任务
...
```

### 步骤 3：重载注册表
- Web UI 点顶栏的 **"↻ 重载 Skills"** 按钮
- 或重启服务
- 或 POST `/skills/reload`

### 步骤 4：测试
在前端输入能命中 keywords 的句子，观察 S1 是否决策调用。

---

## code 型 Skill 编写规范

### 必填：code.py
```python
def main(params: dict) -> dict:
    """
    params 由 SkillLoader 解析并填充
    返回值必须含 'text' 字段（最终展示给用户）
    """
    path = params.get("path", "")
    return {"text": f"读取路径：{path}", "metadata": {...}}
```

### Sandbox API（在 code.py 中可直接用）
- `params: dict` — 调用参数
- `context: dict` — 调用上下文
- `read_file(path, limit=4000) -> str` — 安全读取
- `shell(cmd, timeout=10) -> dict` — 白名单 shell
- `log(msg)` — 广播日志到前端
- `emit(event_type, data)` — 广播事件

### 安全约束
- 文件路径必须在当前项目目录或父目录
- 文件大小 ≤ 1 MB
- 文件类型仅限文本类（.txt/.md/.py/.json/.csv/.log/.yaml/...）
- shell 仅 echo/ls/dir/cat/type/find/where/python

---

## workflow 型 Skill 编写规范

### 必填：workflow.yaml
```yaml
name: my_workflow

steps:
  - skill: web_search
    required: true
    params:
      query: "$user_query"     # 自动替换为用户原始问题
      recency: week

  - skill: summarize
    required: true
    params:
      text: "请基于上面的搜索结果总结"
      length: standard
```

`required: false` 表示该步骤失败时整个 workflow 仍可继续。

---

## 调试技巧

### 查看 skill 完整内容
```
GET /skills/translate
```
返回 meta + 完整 SKILL.md 文本。

### 查看当前注册表
```
GET /skills
```
返回所有 skill 的元数据（不含正文）。

### 健康检查
```
GET /health
```
返回注册表摘要、模型信息、记忆统计。

### 不重启强制重载
```
POST /skills/reload
```

### 不依赖 LLM 的冒烟测试
```
.\start.ps1 smoke
```
验证注册表 / 加载器 / 选择器 / 执行器的基本通路。

---

## 常见问题

**Q: 启动时报 "FTS5 不可用"？**  
A: Python 自带的 sqlite3 通常含 FTS5；如果不可用，混合检索自动降级为纯向量，不影响功能。

**Q: 修改了 SKILL.md 但前端没生效？**  
A: 点顶栏 **"↻ 重载 Skills"** 按钮，或调 `POST /skills/reload`。

**Q: code 型 skill 报错 "路径不在允许范围内"？**  
A: 只能访问当前项目目录及其父目录，不能访问 `C:\` 根目录或其他盘符。

**Q: 怎么让 web_search 真正联网？**  
A: 当前是演示版（LLM 模拟）。生产环境可在 skill 的 SKILL.md 里增加执行真实 API 的 code.py 子 skill，或将 `execution: prompt` 改为自定义 `execution: code` + 接 Tavily/Bing API。

**Q: workflow 类型报错 "缺少 PyYAML"？**  
A: `pip install pyyaml`，setup_env.ps1 已自动安装。

**Q: 如何彻底清空所有状态？**  
A: `.\start.ps1 factory`，或前端点 **"出厂重置"** 按钮。

---

## 命令速查

| 命令 | 作用 |
|------|------|
| `.\setup_env.ps1` | 首次安装 + 配置 API Key |
| `.\start.ps1 cli` | 启动 CLI 对话 |
| `.\start.ps1 web` | 启动 Web UI |
| `.\start.ps1 smoke` | 冒烟测试（不调 LLM）|
| `.\start.ps1 factory` | 出厂重置（清空记忆 + Skill 调用历史）|
| `python src\progressive_agent.py` | 直接启动 CLI |
| `uvicorn src.progressive_serve:app --host 0.0.0.0 --port 8000` | 直接启动 Web |