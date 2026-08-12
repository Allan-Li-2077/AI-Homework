---
name: translate-en
description: >-
  Independent translation sub-skill: translate Chinese into English.
  Called by multi-lang-translate main skill; can also run alone via /skill translate-en.
  Trigger: 翻译英文、英语、English.
disable-model-invocation: true
---

# translate-en

## Role
独立子 Skill：将中文翻译为**英文（English）**。

由主 Skill `multi-lang-translate` 分发调用；也可显式 `@translate-en`。

## Execute

```bash
python skills/translate-en/scripts/run.py "<中文原文>"
```

stdout 最后一行为 JSON：`ok/code/label/text/metrics/skill`。
