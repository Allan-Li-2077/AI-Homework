---
name: demo-greeting
version: 1.0
description: 为指定用户生成个性化问候文本
trigger: 当需要生成问候时触发，支持多种问候风格和语言
dependencies: []
parameters:
  - name: name
    type: str
    required: true
    description: 用户名称
  - name: tone
    type: str
    required: false
    default: friendly
    description: 问候风格（friendly/formal/casual/enthusiastic）
  - name: language
    type: str
    required: false
    default: zh
    description: 语言（zh/en）
returns:
  type: str
  description: 生成的问候文本
---

# 个性化问候生成

## 功能说明

根据用户名称、问候风格和语言偏好，生成个性化的问候文本。

## 示例

```
输入：name="Alice", tone="friendly", language="en"
输出："Hello Alice! 🎉 Hope you're having a wonderful day!"

输入：name="小明", tone="formal", language="zh"
输出："尊敬的小明，祝您您好！"
```

## 参数详解

- **name** (必需，str): 用户名称
- **tone** (可选，str): 问候风格
  - friendly: 友好亲切（默认）
  - formal: 正式礼貌
  - casual: 随意轻松
  - enthusiastic: 热情洋溢

- **language** (可选，str): 使用语言
  - zh: 中文
  - en: 英文

## 执行流程

1. 验证参数完整性
2. 根据 tone 和 language 选择模板
3. 进行变量插值
4. 返回生成的问候文本

## 教学意义

- 演示参数验证与默认值处理
- 展示异步/同步混合调用
- 说明 SkillImpl 接口规范
- 体现 Markdown 配置的自文档化能力
