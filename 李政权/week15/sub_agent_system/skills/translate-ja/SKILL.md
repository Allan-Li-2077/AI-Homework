---
name: translate-ja
description: >-
  Independent translation sub-skill: translate Chinese into Japanese.
  Called by multi-lang-translate main skill; can also run alone via /skill translate-ja.
  Trigger: 翻译日文、日语、Japanese.
disable-model-invocation: true
---

# translate-ja

## Role
独立子 Skill：将中文翻译为**日文（Japanese）**。

由主 Skill `multi-lang-translate` 分发调用；也可显式 `@translate-ja`。

## Execute

```bash
python skills/translate-ja/scripts/run.py "<中文原文>"
```

stdout 最后一行为 JSON：`ok/code/label/text/metrics/skill`。
