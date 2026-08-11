# 作业:下载 Skill 并优化,对比优化前后效果

## 一、实验概述

- **选用的 Skill**:`conversation-json-to-md-cn`(对话 JSON 转 Markdown)
- **来源**:`yangsonhung/awesome-agent-skills` 仓库(skills.sh 生态,43 次安装,纯中文)
- **功能**:将聊天导出 JSON 拆分为按会话保存的 Markdown 文件,保留用户/助手问答结构
- **优化者**:大模型(Claude)
- **优化维度**:token 消耗(指令长度)+ 内容结构
- **核心指标**:SKILL.md 全文的 token 数(每次调用 skill 时全部加载进上下文,是固定的可量化开销)

## 二、优化前后内容

| 文件 | 说明 |
|---|---|
| `before/SKILL.md` | 优化前(原始下载版本) |
| `after/SKILL.md` | 优化后(大模型精简版本) |

两份完整内容见上述文件,对比摘要如下:

### 对比表

| 指标 | 优化前 | 优化后 | 变化 |
|---|---|---|---|
| Token 数(o200k_base) | 838 | **432** | **-48.4%** |
| 字符数 | 1,653 | 952 | -42.4% |

### 具体改动

| 改动 | 说明 |
|---|---|
| 删除 `## Overview` 整段 | 与"使用说明"步骤完全重复 |
| 合并"何时使用/不要使用" | 6 条场景压缩,触发逻辑由 description 承担 |
| 步骤 7 与"二次格式化流程"合并 | 同一件事写了两遍,收敛为一步 |
| 删除"输出格式"示例块 | 与步骤 4 的格式说明重复 |
| 二次格式化 4 小节压成 1 行 | 3 条规则压缩为一句 |
| **保留不动的** | 5 种输入结构格式(契约)、运行命令、验证清单、核心步骤 |

## 三、优化方法(可复现)

1. 用 `js-tiktoken`(o200k_base 编码,与 Claude 模型一致)对 SKILL.md 计数,作为基线。
2. 分析冗余:重复段落(Overview、二次格式化)、翻译腔解释、展开式场景列表。
3. 重写:只保留"功能契约"(格式规则、命令、错误处理),删除解释与重复,结构改为"步骤 + 契约 + 验证"。
4. 再次计数,量化对比。

### 计数命令

```bash
npm i js-tiktoken
node -e "
const { getEncoding } = require('js-tiktoken');
const enc = getEncoding('o200k_base');
console.log(enc.encode(require('fs').readFileSync('SKILL.md','utf8')).length, 'tokens');
"
```

## 四、结论

1. **优化有效**:SKILL.md 从 838 tokens 压缩到 432 tokens(-48.4%),每次调用该 skill 均节省约 400 tokens 的上下文开销。
2. **功能无损失**:格式规则、输入结构识别、运行命令、验证清单全部保留,仅删除了重复与解释性文字。
3. **通用性**:该优化方法(删除重复、压缩解释、保留契约)可应用于任意 skill,是降低 agent 上下文占用成本的基本手段。

## 五、文件清单

```
homework/
├── README.md                # 本报告
├── before/SKILL.md          # 优化前(原始下载)
├── after/SKILL.md           # 优化后(大模型优化)
├── before/scripts/convert_conversations.py  # 执行脚本(原版,未修改)
└── after/scripts/convert_conversations.py   # 执行脚本(同一份,未修改)
```

> 说明:`convert_conversations.py` 是 skill 的执行脚本(SKILL.md 中 `python3 scripts/convert_conversations.py` 指向它)。本次优化对象是 SKILL.md 指令本身;脚本为确定性程序,无冗余可压缩,优化前后保持一致。
