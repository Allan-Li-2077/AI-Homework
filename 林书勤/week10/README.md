# Week 10 - RAG 文档解析工具库汇总

## 作业概述

RAG (Retrieval Augmented Generation) 系统的第一个关键步骤是将各类格式的原始资料转换为可检索的文本。本周作业系统梳理了 Python 生态中常用的文件解析第三方库，帮助快速选型和集成。

## 核心理念

**多使用现成工具，减少重复造轮**。文档解析是 RAG 管道中的基础设施环节，应优先选择成熟的开源库，将精力集中在业务逻辑和检索优化上。

---

## 文件解析库分类索引

### 📄 一、文本类文件

#### Office 文档

- **python-docx / docx2txt**  
  `.docx` Word 文档解析，提取段落、表格、标题  
  适合结构化知识库文档

- **python-pptx**  
  `.pptx` PPT 幻灯片解析，按页面分块  
  适合培训资料入库

- **openpyxl / pandas**  
  `.xlsx/.xls/.csv` 表格解析  
  适合报表、台账、业务数据表向量化

#### 标记语言

- **python-markdown2 / mistune**  
  `.md` Markdown 解析，保留标题层级  
  适合分层切片技术文档

- **json / pyyaml**  
  `.json/.yaml` 结构化数据解析  
  适合 API 文档、配置文件

---

### 📕 二、PDF 文档 (RAG 核心场景)

| 库名 | 优势 | 适用场景 |
|------|------|----------|
| **PyPDF2** | 轻量纯 Python，无依赖 | 简单文字 PDF 快速预处理 |
| **pdfplumber** ⭐ | 精准提取坐标、表格、分栏 | RAG 首选，复杂排版处理 |
| **PyMuPDF (fitz)** | 速度极快，支持图片提取 | 工业级大批量文档处理 |
| **pdfminer.six** | 底层解析器，高度可定制 | 需要自定义切片逻辑时 |

---

### 📷 三、OCR 图文解析

- **pytesseract + Pillow**  
  调用 Tesseract 引擎，支持多语言  
  低成本本地 OCR 方案

- **paddleocr** ⭐  
  百度开源，开箱即用，内置中文模型  
  支持倾斜矫正、表格识别，**强烈推荐**

- **layoutlm / doclayout-yolo**  
  文档布局检测，区分标题/段落/表格  
  配合 OCR 实现智能分块

---

### 📚 四、电子书与富文本

- **ebooklib / Calibre-python**  
  `.epub/.mobi` 电子书解析  
  按章节自动分割

- **beautifulsoup4 + lxml**  
  `.html/.htm` 网页文档解析  
  清除标签，提取正文

- **striprtf**  
  `.rtf` 富文本解析  
  去除控制符

---

### 🎬 五、音视频字幕

- **pysrt / webvtt-py**  
  `.srt/.vtt` 字幕文件解析  
  按时间轴分段入库

- **ffmpeg + whisper (OpenAI)**  
  音视频转文字  
  适合会议录音、课程视频知识库

---

### 📦 六、压缩包批量处理

- **zipfile / tarfile** (Python 内置)  
  `.zip/.tar` 解压，遍历内部文档

- **unrar**  
  `.rar` 解压，批量读取

---

## 🚀 一站式整合框架 (推荐)

无需手动组合各类库，开箱即用：

1. **LlamaIndex SimpleDirectoryReader**  
   自动识别格式，直接输出 Document 文本块

2. **LangChain DocumentLoaders**  
   分格式加载器：PyPDFLoader、Docx2txtLoader 等

3. **Unstructured.io** ⭐  
   全能解析库，支持数十种格式  
   自动布局分块 + OCR，**企业级 RAG 主流方案**

---

## 📋 选型速查表

| 场景 | 推荐库 |
|------|--------|
| 通用混合文档 | `unstructured` / LangChain 加载器 |
| 纯文字 PDF 高精度 | `pdfplumber` |
| 大批量高速 PDF | `PyMuPDF (fitz)` |
| 扫描件 OCR | `paddleocr` |
| Excel 知识库 | `openpyxl + pandas` |
| 网页离线文档 | `beautifulsoup4` |
| 电子书 EPUB | `ebooklib` |
| 语音视频转文本 | `openai-whisper` |

---

## 总结

RAG 文档解析的核心是**根据数据源特点选择合适工具**：

- 格式单一、数据规范 → 专用库 (如 pdfplumber)
- 格式混杂、需要快速迭代 → 整合框架 (如 Unstructured)
- 扫描件、图片多 → OCR 优先 (如 paddleocr)

完整代码演示见课上资料。
