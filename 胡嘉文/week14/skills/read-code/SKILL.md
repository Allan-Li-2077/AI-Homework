---
name: read-code
description: 读取并理解项目代码，输出一个自包含的 HTML 代码地图（代码结构、模块职责、调用链路、关键逻辑），辅助快速上手与讲解演示
type: procedure
version: 1
---

# read-code — 代码结构与逻辑梳理

读取一个项目（或指定目录/文件）的代码，输出一个**自包含的 HTML 文件**，
用可视化的方式讲清楚「这个项目由哪些模块组成、它们怎么协作、核心逻辑是什么」。
产物面向**帮助人快速理解代码**，而不是 API 参考文档的堆砌。

## 触发条件

用户提出以下任一意图时使用本技能：

- "帮我看看这个项目 / 讲解一下代码结构"
- "梳理一下这个代码库，出一份文档"
- "这个项目是怎么跑起来的 / 入口在哪"
- "这段代码的核心逻辑是什么 / 想改应该动哪里"
- "生成一个代码地图 / 架构说明"

## 工作流程

严格按「先全貌、后局部、再链路」的顺序执行：

### 1. 概览摸底
- 读取根目录说明文档：README / CLAUDE.md / 项目文档
- 读取工程配置文件：`package.json` / `requirements.txt` / `pyproject.toml` / `go.mod` 等，
  确认技术栈、依赖、脚本命令
- 列出目录树（排除 `node_modules` / `.git` / `__pycache__` / 构建产物），掌握整体边界

### 2. 定位入口
- 找出程序入口：`main` 函数 / 路由注册 / 启动脚本 / 构建配置指向的入口文件
- 记录「如何运行」：启动命令、端口、必需的环境变量

### 3. 逐模块梳理职责
- 对每个核心目录/文件，明确它「负责什么、不负责什么」
- 关键文件标注：路径、行号、核心函数、对外接口

### 4. 追踪关键调用链路
- 从入口出发走一遍主流程（如一次请求 / 一次数据处理）
- 记录数据或控制流经过的模块顺序，识别：分层关系、依赖方向、有无循环依赖

### 5. 提炼关键逻辑
- 核心算法、易错点、边界处理、异常分支
- 能通过 git log / 注释确认「为什么这么写」就查，查不到的不猜

### 6. 生成 HTML
按下方输出规范把以上信息组织进一个自包含 HTML 文件并保存。

## HTML 输出规范

### 硬性要求
- **单个 `.html` 文件，完全自包含**：CSS 内联，禁止外链 CDN / 外部字体 / 外部脚本（必须可离线打开）
- `<!DOCTYPE html>` + `<html lang="zh-CN">`，UTF-8 编码
- 默认文件名 `{项目名}-code-map.html`，保存到项目根目录或用户指定路径；写完后告知用户文件路径
- 所有代码引用必须与真实代码一致，**不允许编造文件、行号或逻辑**

### 页面结构（自上而下）
1. **页头**：项目名、一句话简介、技术栈标签、运行方式（启动命令）
2. **目录结构**：带职责注释的目录树（关键节点标注文件/行号）
3. **模块清单**：表格列出每个核心文件/模块 → 职责 → 关键函数/入口 → 备注
4. **调用链路**：主流程的编号步骤；链路复杂时配一张简单 SVG 流程图（入口到出口，标清数据流方向）
5. **关键逻辑**：核心函数/算法的文字拆解 + 代码片段引用（标 `文件:行号`）
6. **扩展指南**：「想改什么 → 改哪里」对照表，每行对应到真实文件行号

### 导航与样式
- 左侧固定侧边栏 TOC，锚点跳转；内容过长的部分用 `<details>` 折叠
- 简洁干净：系统字体栈、单一强调色、浅色背景；表格/代码块/流程图风格统一
- 支持浏览器内 Ctrl+F 定位；`@media print` 时隐藏侧边栏

## 质量要求
- **忠于代码**：每个结论都有代码依据；不确定的内容标注「待确认」，不臆测
- **结构优先**：先让读者建立骨架认知，再深入细节
- **可扫读**：善用表格、列表、编号步骤；段落克制
- **粒度得当**：小项目逐文件讲，大项目按模块分层讲，避免平铺

## HTML 模板骨架

以下为推荐骨架，直接按其结构填充内容：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{项目名} — 代码地图</title>
<style>
  :root { --accent:#2f6fed; --bg:#fafbfc; --text:#1f2328;
          --muted:#57606a; --border:#d0d7de; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;
         background:var(--bg); color:var(--text); line-height:1.7; }
  .layout { display:flex; min-height:100vh; }
  aside { width:260px; position:sticky; top:0; height:100vh; overflow-y:auto;
          border-right:1px solid var(--border); padding:16px; background:#fff; }
  aside a { display:block; padding:4px 8px; color:var(--muted); text-decoration:none;
            border-radius:6px; }
  aside a:hover { background:#f0f3f6; color:var(--accent); }
  main { flex:1; padding:24px 40px; max-width:960px; }
  h1 { font-size:1.8em; } h2 { border-bottom:1px solid var(--border);
       padding-bottom:6px; margin-top:2em; }
  table { border-collapse:collapse; width:100%; }
  th,td { border:1px solid var(--border); padding:6px 10px; text-align:left;
          font-size:.95em; }
  code { background:#eff1f3; border-radius:4px; padding:1px 5px;
         font-family:ui-monospace,Consolas,monospace; }
  pre { background:#fff; border:1px solid var(--border); border-radius:8px;
        padding:12px; overflow-x:auto; }
  details { border:1px solid var(--border); border-radius:8px; padding:8px 12px;
            margin:8px 0; background:#fff; }
  .tag { display:inline-block; background:#eef3ff; color:var(--accent);
         border-radius:999px; padding:1px 10px; font-size:.85em; margin-right:6px; }
  @media print { aside { display:none; } main { max-width:none; padding:0; } }
</style>
</head>
<body>
<div class="layout">
  <aside>
    <strong>{项目名}</strong>
    <nav>
      <a href="#overview">项目概览</a>
      <a href="#structure">目录结构</a>
      <a href="#modules">模块清单</a>
      <a href="#flow">调用链路</a>
      <a href="#key-logic">关键逻辑</a>
      <a href="#extend">扩展指南</a>
    </nav>
  </aside>
  <main>
    <h1>{项目名} <span class="tag">技术栈</span></h1>
    <p>一句话简介 + 运行方式</p>

    <h2 id="overview">项目概览</h2>
    <p>核心功能 / 启动命令 / 端口 / 环境变量</p>

    <h2 id="structure">目录结构</h2>
    <pre>带注释的目录树</pre>

    <h2 id="modules">模块清单</h2>
    <table>
      <tr><th>文件</th><th>职责</th><th>关键函数/入口</th><th>备注</th></tr>
      <tr><td><code>src/xxx.py</code></td><td>…</td><td>…</td><td>…</td></tr>
    </table>

    <h2 id="flow">调用链路</h2>
    <ol><li>步骤 1 …</li></ol>
    <svg viewBox="0 0 600 200">…简单流程图…</svg>

    <h2 id="key-logic">关键逻辑</h2>
    <p>核心算法 / 易错点拆解</p>

    <h2 id="extend">扩展指南</h2>
    <table><tr><th>想改什么</th><th>改哪里</th></tr></table>
  </main>
</div>
</body>
</html>
```

## 边界与禁忌
- 不读 `node_modules` / `.git` / 构建产物；超大文件只读关键片段
- 不编造代码内容与调用关系；拿不准的链路标注「待确认」
- 不要写成 API 参考文档——本技能只回答「结构是什么、怎么协作、改哪里」

<!-- v1: 初始版本 -->
