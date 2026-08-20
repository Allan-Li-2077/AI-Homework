# 📚 Flash Card 快速参考

## 一句话说明
为英语单词生成精美的HTML学习闪卡，包含音标、释义、近义词和3条例句。

## 最快的5步流程

```bash
# 1️⃣ 进入目录
cd week14/flash-card-mini

# 2️⃣ 复制并编辑示例
cp data/example.json data/your_word.json
# 修改data/your_word.json中的 word, phonetic, definition, examples 等字段

# 3️⃣ 验证数据（可选但推荐）
python scripts/make_flashcard.py data/your_word.json --check

# 4️⃣ 生成闪卡
python scripts/make_flashcard.py data/your_word.json

# 5️⃣ 在浏览器打开
# Windows: start your_word.html
# Mac: open your_word.html
# Linux: xdg-open your_word.html
```

## JSON 最小完整模板

```json
{
  "word": "example",
  "phonetic": "/ɪɡˈzæmpəl/",
  "pos": "n.",
  "definition": "例子；范例",
  "synonyms": ["instance", "case", "sample", "model"],
  "examples": [
    {
      "en": "Can you give me an example?",
      "zh": "你能给我一个例子吗？"
    },
    {
      "en": "This is a good example of modern architecture.",
      "zh": "这是现代建筑的一个很好的例子。"
    },
    {
      "en": "We should set a good example for our children.",
      "zh": "我们应该为孩子们树立一个好榜样。"
    }
  ]
}
```

## 常用命令

```bash
# 生成到当前目录（默认）
python scripts/make_flashcard.py data/word.json

# 生成到指定路径
python scripts/make_flashcard.py data/word.json -o ~/Desktop/word.html

# 快速验证JSON数据
python scripts/make_flashcard.py data/word.json --check

# 显示帮助
python scripts/make_flashcard.py --help
```

## ⚠️ 常见错误及解决

| 错误 | 原因 | 解决 |
|------|------|------|
| `缺少必需字段` | JSON缺少必需项 | 检查是否有 word/phonetic/pos/definition |
| `例句不足` | examples数组少于3条 | 添加到恰好3条 |
| `JSON 格式错误` | JSON语法不合法 | 用jsonlint验证或检查引号/逗号 |
| `文件不存在` | 路径错误 | 确保data/word.json文件存在 |

## 🎯 字段填写要点

- **word**: 小写英文单词（如 `resilient`）
- **phonetic**: 用 `/音标/` 格式（参考phonetic app或词典）
- **pos**: 词性（`n.` `v.` `adj.` `adv.` 等）
- **definition**: 简洁的中文解释（1-2句）
- **synonyms**: 4-6个近义词列表
- **examples**: 恰好3条，每条包含 `en` 和 `zh`

## ✨ 特色功能

✅ 点击音标可一键复制  
✅ 响应式设计（手机/平板/电脑都好看）  
✅ 优雅的交互动画效果  
✅ 数据验证确保质量  

## 📂 目录结构

```
flash-card-mini/
├── scripts/
│   └── make_flashcard.py      # 主程序
├── data/
│   └── example.json           # 示例数据
├── SKILL.md                   # 详细文档
└── resilient.html             # 生成的闪卡示例
```

---

💡 **提示**: 定期为常用单词生成闪卡，通过多次复习加强记忆效果！
