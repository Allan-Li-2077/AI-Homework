# 开发者指南

适合想要修改、扩展或贡献代码的开发者。

## 🏗️ 项目架构

### 文件职责划分

```
make_flashcard.py
├─ TEMPLATE          CSS+HTML模板字符串
├─ validate_data()   数据验证逻辑
├─ build()          HTML生成
├─ main()           CLI入口
└─ argparse配置     命令行参数

data/
├─ example.json     参考模板
└─ *.json           用户创建的单词数据

生成文件
└─ *.html           静态闪卡页面
```

### 数据流

```
input.json → validate_data() → build() → output.html
              ▲                  ▲
              │                  │
           检查字段           渲染模板
           检查例句           HTML转义
```

## 🔧 代码改进指南

### 添加新的CLI参数

```python
# 在main()函数中添加
p.add_argument(
    "--theme",                    # 参数名
    choices=["light", "dark"],    # 可选值
    default="light",              # 默认值
    help="选择主题（浅色/深色）"
)
```

然后在build()中使用：
```python
def build(d, theme="light"):
    # 根据theme选择CSS变量
    ...
```

### 扩展validate_data()

```python
def validate_data(data):
    # ... 现有检查 ...
    
    # 新增检查：单词长度
    if len(data["word"]) > 20:
        return False, "单词过长（最多20个字符）"
    
    # 新增检查：近义词数量
    if len(data.get("synonyms", [])) < 4:
        return False, "近义词不足（至少4个）"
    
    return True, None
```

### 修改CSS样式

原模板在TEMPLATE字符串的`<style>`部分。
```html
<style>
:root{--bg:#f5f7fb;...}    /* 改这里调整颜色 */
.card{...}                  /* 改这里调整卡片样式 */
</style>
```

**建议**：CSS规则保持单行格式以维持token压缩效果。

## 📝 JSON数据规范

### 必需字段

| 字段 | 类型 | 说明 | 验证 |
|------|------|------|------|
| `word` | str | 单词（小写） | 非空 |
| `phonetic` | str | 音标 | 非空 |
| `pos` | str | 词性（n./v./adj.等） | 非空 |
| `definition` | str | 中文释义 | 非空 |
| `examples` | list | 恰好3条例句 | len==3 |
| `synonyms` | list | 4-6个近义词 | len >= 4 |

### examples字段结构

每条例句必须是object：
```json
{
  "en": "英文原文",
  "zh": "中文翻译"
}
```

**验证规则**：
- 恰好3条
- 每条都有en和zh
- 不能为空字符串

### 字段验证顺序

```python
def validate_data(data):
    # 1. 必需字段存在性
    if not data.get("word"):
        return False, "缺少word字段"
    
    # 2. 字段内容有效性
    if not data["word"].replace("-", "").isalpha():
        return False, "word只能包含字母和连字符"
    
    # 3. 集合字段数量
    if len(data.get("examples", [])) != 3:
        return False, "examples必须恰好3条"
    
    # 4. 嵌套对象完整性
    for i, ex in enumerate(data["examples"]):
        if "en" not in ex or "zh" not in ex:
            return False, f"例句{i+1}缺少en或zh"
```

## 🎨 UI自定义

### 修改色系

编辑TEMPLATE中的`:root`变量：

```css
:root{
  --bg:#f5f7fb;        /* 背景色 */
  --ink:#1f2937;       /* 文字色 */
  --accent:#4f46e5;    /* 强调色 */
  --soft:#eef2ff;      /* 柔和背景 */
}
```

### 快速主题预设

深色主题配置：
```css
:root{
  --bg:#1a1a1a;
  --ink:#f0f0f0;
  --accent:#7c3aed;
  --soft:#2d2d2d;
}
```

### 修改字体

找到body规则：
```css
body{
  font-family:-apple-system, BlinkMacSystemFont, ...;
}
```

改为其他字体（保持fallback链）。

## 🧪 测试流程

### 单元测试 - 验证函数

```python
# test_flashcard.py
from make_flashcard import validate_data

def test_valid_data():
    data = {
        "word": "test",
        "phonetic": "/test/",
        "pos": "n.",
        "definition": "测试",
        "examples": [
            {"en": "e1", "zh": "z1"},
            {"en": "e2", "zh": "z2"},
            {"en": "e3", "zh": "z3"},
        ],
        "synonyms": ["s1", "s2", "s3", "s4"]
    }
    valid, err = validate_data(data)
    assert valid == True, f"应该验证通过，但出错: {err}"

def test_missing_field():
    data = {"word": "test"}  # 缺少其他字段
    valid, err = validate_data(data)
    assert valid == False, "应该验证失败"
```

### 集成测试 - HTML生成

```bash
# 1. 验证示例JSON
python scripts/make_flashcard.py data/example.json --check
✓ 数据有效 (resilient)

# 2. 生成HTML
python scripts/make_flashcard.py data/example.json
✓ 已生成: resilient.html

# 3. 检查输出
# - 文件存在
# - 文件大小合理（>2KB）
# - 包含所有数据（word, phonetic, examples等）
```

## 🚀 扩展方向

### 中等难度扩展

**1. 支持多语言界面**
```python
TEMPLATES = {
    "zh": "...",  # 中文模板
    "en": "...",  # 英文模板
}

def build(d, lang="zh"):
    template = TEMPLATES.get(lang, TEMPLATES["zh"])
    return template.format(...)
```

**2. 支持自定义CSS**
```bash
python make_flashcard.py data/word.json --css styles.css
```

**3. 批量生成**
```bash
python make_flashcard.py data/ --batch
# 生成data/目录下所有JSON文件对应的HTML
```

### 高难度扩展

**1. 支持PDF导出**
- 需要集成pdfkit或reportlab
- 生成带样式的PDF版本

**2. 支持Markdown输入**
```
# resilient /rɪˈzɪliənt/ (adj.)
有韧性的；能快速恢复的

## 近义词
- flexible
- adaptable
...
```

**3. 服务化**
```python
from flask import Flask, request
app = Flask(__name__)

@app.route("/generate", methods=["POST"])
def api_generate():
    data = request.json
    valid, err = validate_data(data)
    if not valid:
        return {"error": err}, 400
    html = build(data)
    return {"html": html}
```

## 📊 性能优化

### 当前瓶颈
- HTML字符串生成（现在<1ms）
- 文件I/O（现在<10ms）

### 可优化方向
- 预编译模板（Jinja2）→ 更快的渲染
- 批量处理 → 并行生成多个卡片
- 缓存 → 相同JSON内容重用HTML

### Jinja2优化示例

```python
from jinja2 import Template

TEMPLATE_JINJA = Template("""
<!DOCTYPE html>
...
<h1 class="word">{{ word }}</h1>
<div class="phonetic">{{ phonetic }}</div>
...
{% for syn in synonyms %}
<span class="tag">{{ syn }}</span>
{% endfor %}
...
""")

def build_fast(d):
    return TEMPLATE_JINJA.render(
        word=d["word"],
        phonetic=d["phonetic"],
        synonyms=d["synonyms"],
        ...
    )
```

## 🐛 常见问题排查

### HTML生成成功但显示有问题

1. **中文显示乱码**
   - 检查JSON文件编码（必须UTF-8）
   - 检查HTML的charset meta标签

2. **样式不生效**
   - CSS变量可能被覆盖
   - 检查浏览器开发者工具Console

3. **交互功能不工作**
   - 检查JavaScript是否执行（浏览器Console）
   - 尝试用不同浏览器测试

### 验证失败

```bash
python make_flashcard.py data/word.json --check

# 常见错误信息及解决

❌ 缺少必需字段: pos, definition
→ JSON中需要添加pos和definition字段

❌ 例句不足（需3条，当前1条）
→ examples数组需要恰好3个object

❌ 例句1缺少en或zh字段
→ 检查examples[0]是否有en和zh字段
```

## 📚 代码规范

### 命名规范
- 函数名：snake_case (`validate_data`)
- 常量：UPPER_CASE (`TEMPLATE`)
- 变量：snake_case (`output_path`)

### 代码风格
- 保持代码紧凑（便于token压缩）
- 但要注意可读性
- 使用类型提示（如有）

```python
def validate_data(data: dict) -> tuple[bool, str | None]:
    """验证数据"""
    ...
```

### 文档规范
- 函数需要docstring
- 复杂逻辑需要注释
- 参数列表保持简洁

---

## 相关资源

- 🌐 Jinja2文档：https://jinja.palletsprojects.com/
- 🐛 argparse教程：https://docs.python.org/3/library/argparse.html
- 🎨 CSS参考：https://developer.mozilla.org/zh-CN/docs/Web/CSS

---

**最后更新**：2026-08-21
