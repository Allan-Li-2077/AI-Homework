---
name: file_reader
version: 1.0.0
description: 读取本地文本/代码文件，提取摘要或回答用户关于文件内容的问题
keywords: [读文件, read file, 文件内容, 打开, cat, 看看, 文档内容]
triggers: [file_read_request]
execution: code
parameters:
  - name: path
    type: string
    required: true
    description: 文件绝对路径（限 .txt / .md / .py / .json / .csv / .log 等文本文件）
  - name: question
    type: string
    required: false
    description: 针对文件内容的具体问题（不填则返回前 2000 字符 + 文件元信息）
  - name: max_chars
    type: string
    required: false
    description: 最大返回字符数（默认 4000）
---

# File Reader Skill（Code 执行型）

这是 **execution=code** 类型的 skill。它通过 sandbox 执行同目录下的 `code.py`，**不调用 LLM** 直接读取文件。

## 行为
1. 校验 `path` 是允许的文本后缀
2. 用 sandbox API 中的 `read_file()` 安全读取（限制最大字符数）
3. 如果有 `question`，**回退到 LLM** 基于文件内容回答（这部分由 harness 自动处理）
4. 返回结构化结果：`{text, metadata, preview}`

## 安全约束（由 SkillExecutor 强制）
- `path` 必须在当前项目根目录或用户显式允许的白名单内
- 文件大小限制（默认 1 MB）
- 文件类型白名单（拒绝 .exe/.dll/.bin 等二进制）
- 无文件系统写权限
- 无 subprocess 执行任意命令（仅 echo/ls/dir/cat/type 等白名单）

## 输入参数
- 路径：`{{path}}`
- 问题：`{{question | default:}}`
- 字符上限：`{{max_chars | default:4000}}`

详细执行逻辑见 `code.py`。