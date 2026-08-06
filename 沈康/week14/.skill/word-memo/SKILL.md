---
name: word-memo
description: >-
  为一个英语单词生成静态 HTML 记忆卡，突出派生词与联想记忆（并含词根、释义、关联词、例句），帮助高效记单词。
  Use when the user asks to memorize / 记 an English word or wants its derivatives / 派生词 / 联想记忆,
  e.g. "记一下 abandon 这个单词"、"给我 abandon 的派生词和联想记忆"、"帮我记 benefit"。
phase: OUTPUT
kind: script
entry: scripts/make_memo.py
manual: true
---

# Word Memo 单词记忆卡生成

输入一个英语单词，输出一张静态 HTML 记忆卡，重点给出**派生词**与**联想记忆**。
版面顺序与各版块**数量下限**由脚本同目录的 `config.json` 决定（`section_order` / `min_counts` /
`optional_sections`），该文件由 harness 的自进化功能自动维护。默认版面：
单词+音标 → 释义 → 词根词缀 → 派生词 → 联想记忆 → 关联词 → 例句。

## 触发场景

- "记一下 abandon 这个单词"
- "给我 abandon 的派生词和联想记忆"
- "帮我记 benefit，要词根和派生词"
- "给我 resilient 的联想记忆"

## 执行流程

1. **识别单词**：从用户话语中提取目标英语单词（小写化作为文件名）。

2. **自己产出该单词的完整记忆内容**（这是本 skill 的关键，不能跳过）：
   你就是词典。基于自身知识，为该单词写出音标、词性、中文释义、词根词缀拆解、
   派生词、联想记忆、关联词、例句——**这些内容由你生成，绝不能留空让脚本去隐藏版块**。

3. **生成 HTML**：把上一步产出的内容作为命令行参数传给脚本，一次 `run_command` 完成：
   ```bash
   python .skill/word-memo/scripts/make_memo.py --word <word> \
     --phonetic "<音标>" --pos "<词性>" --definition "<中文释义>" \
     --root "<词根词缀拆解一句话>" \
     --deriv "<派生词>|<词性>|<释义>" --deriv "..." \
     --mnemonic "<联想记忆一条>" --mnemonic "..." \
     --syn <近义词> --ant <反义词> --theme <同主题词> \
     --example "<英文例句>||<中文翻译>" --example "..." \
     -o output/<word>.html
   ```
   **必须填齐的核心字段（缺一不可）**：
   - `--word`：单词本身。
   - `--phonetic`：音标（如 `/əˈbændən/`）。
   - `--pos`：词性（如 `v. / n.`）。
   - `--definition`：中文释义。
   - `--root`：词根词缀拆解一句话。
   - `--deriv "word|pos|meaning"`：**派生词，本 skill 核心**，竖线分三段，可重复，优先高频。
   - `--mnemonic "文本"`：**联想记忆，本 skill 核心**，可重复，谐音/画面/构词故事，要生动具体。

   **各版块数量下限见 `config.json` 的 `min_counts`**（默认 deriv≥3、mnemonic≥2、example≥2、
   syn≥3、ant≥2、theme≥3）。请按 config 当前值供给足量内容——config 可能被自进化调整过，
   以其为准；宁可多给不要少给。

   建议补充（尽量给，让卡片更完整）：
   - `--syn / --ant / --theme <词>`：近义/反义/同主题词，数量参照 config 的 `min_counts`。
   - `--example "英文||中文"`：例句，双竖线分中英，数量参照 config 的 `min_counts.example`。

4. **打开预览**：用默认浏览器打开 `output/<word>.html`。

## 注意事项

- **绝不允许只传 `--word` 就跑脚本**。只有单词、没有派生词/联想/释义的卡片是"空卡"，属于错误产出。
- `--deriv`、`--mnemonic` 是本 skill 的核心价值，任何情况下都必须填写；其余字段尽量填齐。
- 脚本的"字段可缺省、缺省版块自动隐藏"只是**容错兜底**，不是让你偷懒省略内容的理由。
- **版面与显隐由 `config.json` 驱动**：脚本会读同目录 `config.json`，按 `section_order` 排布版块，
  按 `optional_sections` 决定 root/association/example 是否展示（deriv/mnemonic 为核心，永不隐藏）。
  你无需关心 config，只管按 `min_counts` 供足内容即可；显隐/顺序交给脚本。
- 产物 HTML 统一输出到项目根 `output/` 目录（脚本默认即落 `output/<word>.html`；如需指定路径可加 `-o`）。
- `data/` 目录仅存放样例数据（如 `abandon.json`），供参考与回归测试用；正常流程用命令行字段直传，无需写 JSON 文件。
