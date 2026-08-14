---
name: translate-fr
description: >-
  Independent translation sub-skill: translate Chinese into French.
  Called by multi-lang-translate main skill; can also run alone via /skill translate-fr.
  Trigger: 翻译法语、法文、French.
disable-model-invocation: true
---

# translate-fr

## Role
独立子 Skill：将中文翻译为**法语（French）**。

由主 Skill `multi-lang-translate` 分发调用；也可显式 `@translate-fr`。

## Execute

```bash
python skills/translate-fr/scripts/run.py "<中文原文>"
```

stdout 最后一行为 JSON：`ok/code/label/text/metrics/skill`。
