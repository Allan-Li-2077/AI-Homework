---
name: multi-lang-translate
description: >-
  多语言翻译主 Skill：解析意图后调用五个独立子 Skill
 （translate-en / translate-ja / translate-fr / translate-ko / translate-ru）。
  支持并行或串行（TRANSLATE_PARALLEL / API）。
  触发词：翻译英文、翻译日文、翻译成法语、译成韩语、译成俄语等。
  不支持的语种会提示「抱歉，不支持翻译该种语言」。
---

# Multi-language Translate（主 Skill + 独立子 Skill）

## Architecture
```
用户消息
  → multi-lang-translate（主 Skill / TranslateMainAgent）
       ├─ skills/translate-en   英文
       ├─ skills/translate-ja   日文
       ├─ skills/translate-fr   法语
       ├─ skills/translate-ko   韩语
       └─ skills/translate-ru   俄语
```

- 五个语言能力是**独立 Skill 包**（各自有 `SKILL.md` + `scripts/run.py`）
- 主 Skill 负责解析、分发、汇总；子 Skill 只做单语种翻译
- **并行 / 串行**开关：`TRANSLATE_PARALLEL=1|0`，或 `GET/POST /translate/config`

## Supported targets
| 触发说法 | 子 Skill |
|---------|----------|
| 英文 / 英语 / English | `translate-en` |
| 日文 / 日语 / Japanese | `translate-ja` |
| 法语 / 法文 / French | `translate-fr` |
| 韩语 / 韩文 / Korean | `translate-ko` |
| 俄语 / 俄文 / Russian | `translate-ru` |

目标语言不在以上五种时，回复：**抱歉，不支持翻译该种语言**

## When to use
- 「请翻译成英文：今天天气很好」
- 「把这段话翻译英文和韩语：春天来了」
- 「翻译成德语：你好」（应提示不支持）
- 显式：`/skill multi-lang-translate` 或 `@multi-lang-translate`

## Execute（必须跑脚本）

```bash
python skills/multi-lang-translate/scripts/translate.py "<用户原文>"
# 可选：--parallel / --serial / --dry-run
```

成功时 stdout 最后一行为 JSON（含 `mode`、`sub_skill_runs`、`translations`、`display`）。

## Response rules
对外回复**必须**使用统一格式，原样输出 Skill 结果，不要改写：

```
并行模式

英文：
Hello

韩语：
안녕하세요

用时 12.212s，Token 3319
```

不支持的语种（无可用目标时）仅回复：
```
抱歉，不支持翻译该种语言
```

- 开头展示「并行模式」或「串行模式」
- 每种语言用「语言名：」引导，下一行是译文
- 末尾展示耗时与 Token
- 不要重新翻译或编造脚本未返回的译文
