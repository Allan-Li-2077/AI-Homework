---
name: flash-card-mini
description: >-
  为英语单词生成静态 HTML 学习闪卡（音标、词性、释义、3 条中英对照例句、近义词）。
  Use when 用户要做某个英语单词的 flash card / 闪卡 / 单词卡。
---

# Flash Card 生成器

版面顺序：单词+音标 → 释义 → 近义词 → 3 条例句。

## 快速开始

1. **识别单词**：从用户话语中提取目标单词（小写）。

2. **创建 JSON 数据** 到 `data/<word>.json`（skill 目录下）：
   ```json
   {
     "word": "resilient",
     "phonetic": "/rɪˈzɪliənt/",
     "pos": "adj.",
     "definition": "有韧性的；能快速恢复的；有适应力的",
     "synonyms": ["flexible", "adaptable", "tough", "strong", "robust", "sturdy"],
     "examples": [
       {
         "en": "The economy has proven resilient in the face of challenges.",
         "zh": "该经济在面对挑战时已证明具有韧性。"
       },
       {
         "en": "Resilient plants can survive in harsh conditions.",
         "zh": "有韧性的植物能在恶劣环境中存活。"
       },
       {
         "en": "Building a resilient mindset takes time and practice.",
         "zh": "培养有韧性的心态需要时间和练习。"
       }
     ]
   }
   ```

3. **生成 HTML**（输出到当前工作目录 `./<word>.html`，`-o` 可指定路径）：
   ```bash
   python <skill_dir>/scripts/make_flashcard.py <skill_dir>/data/<word>.json
   python <skill_dir>/scripts/make_flashcard.py <skill_dir>/data/<word>.json -o /custom/path/output.html
   ```

4. **验证数据**（可选，检查 JSON 合法性）：
   ```bash
   python <skill_dir>/scripts/make_flashcard.py <skill_dir>/data/<word>.json --check
   ```

5. **打开预览**：用默认浏览器打开生成的 HTML 文件。

## 数据字段规范

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `word` | string | ✓ | 英文单词（小写） |
| `phonetic` | string | ✓ | 音标符号，如 `/ˈæktɪv/` |
| `pos` | string | ✓ | 词性标记，如 `adj.`, `v.`, `n.` |
| `definition` | string | ✓ | 中文释义 |
| `synonyms` | array | ✓ | 4-6 个近义词 |
| `examples` | array | ✓ | 恰好 3 条例句对象 |

### examples 格式
每条例句必须包含：
- `en` (string): 英文原文，地道且体现典型用法
- `zh` (string): 中文翻译，准确传达含义

## 特性

- ✨ **响应式设计**：适配各种屏幕尺寸
- 🎨 **优雅配色**：专业美观的配色方案
- ⚡ **交互增强**：点击音标可一键复制
- 🛡️ **数据验证**：检查 JSON 数据完整性
- 📊 **错误提示**：清晰的错误消息指导修复


