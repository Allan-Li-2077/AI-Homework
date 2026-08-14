---
name: translate-ko
description: >-
  Independent translation sub-skill: translate Chinese into Korean.
  Called by multi-lang-translate main skill; can also run alone via /skill translate-ko.
  Trigger: 翻译韩语、韩文、Korean.
disable-model-invocation: true
---

# translate-ko

## Role
独立子 Skill：将中文翻译为**韩语（Korean）**。

由主 Skill `multi-lang-translate` 分发调用；也可显式 `@translate-ko`。

## Execute

```bash
python skills/translate-ko/scripts/run.py "<中文原文>"
```

stdout 最后一行为 JSON：`ok/code/label/text/metrics/skill`。
