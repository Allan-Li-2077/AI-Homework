---
name: conversation-json-to-md-cn
description: 将聊天导出 JSON 拆分为按会话保存的 Markdown,保留用户/助手问答结构。
---

# Conversation JSON 转 Markdown

将聊天导出 JSON 转为 Markdown:按会话拆文件,只留用户/助手问答,回答内 Markdown 保留,导出后二次规范化。

## 步骤

1. 读取用户提供的输入文件路径(不假设默认文件名)。
2. 自动识别 JSON 结构,提取会话。
3. 每会话导出 1 个 `.md` 文件;只保留用户/助手问答。
4. 问答格式:`## <问题>` + `### 回答`;保留回答内 Markdown,内部标题降 1 级。
5. 二次格式化:文件名仅用会话标题(清非法字符、重名加 ` (2)` 序号);结构 一级=会话标题、二级=问题、回答= `### 回答`;修正后再交付。

## 支持的输入结构

- DeepSeek/ChatGPT:`mapping/root/children/fragments`
- Qwen:`data[].chat.messages[]`、`content_list`(优先 `phase=answer`)
- Claude 网页导出:`list[{ name, chat_messages }]`
- 通用消息数组:`messages/history/conversations/dialog/turns`
- 成对字段:`question-answer`、`prompt-response`、`input-output`

无法识别时:停下,向用户要样例片段,再扩展解析规则。

## 运行脚本

```bash
python3 scripts/convert_conversations.py --input <用户提供的.json> --output-dir <输出目录> --clean
```

## 验证清单

- 导出文件数 = 会话数
- 文件名无随机后缀
- 无 `## REQUEST` / `## RESPONSE`
- 回答统一 `### 回答`
- Markdown 渲染正常
