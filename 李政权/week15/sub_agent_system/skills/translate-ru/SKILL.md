---
name: translate-ru
description: >-
  Independent translation sub-skill: translate Chinese into Russian.
  Called by multi-lang-translate main skill; can also run alone via /skill translate-ru.
  Trigger: 翻译俄语、俄文、Russian.
disable-model-invocation: true
---

# translate-ru

## Role
独立子 Skill：将中文翻译为**俄语（Russian）**。

由主 Skill `multi-lang-translate` 分发调用；也可显式 `@translate-ru`。

## Execute

```bash
python skills/translate-ru/scripts/run.py "<中文原文>"
```

stdout 最后一行为 JSON：`ok/code/label/text/metrics/skill`。
