# 白酒年报智能客服（Week10）

基于 **DeepSeek** + **阿里云 Embedding** + **本地 Chroma RAG** 的智能客服 Demo。

## 功能

1. 使用 DeepSeek 大模型对话  
2. 本地 Chroma 向量库做 RAG  
3. 知识库：贵州茅台、五粮液、泸州老窖、习酒（2022–2025 年报摘录）  
4. 年报相关提问 → RAG 检索后回答；非白名单公司年报 → `暂无相关知识`  
5. 非年报提问 → 直接调用 DeepSeek  
6. 向量由阿里云 `text-embedding-v3` 生成（未配置密钥时使用本地确定性向量，仅供联调）

## 目录

```text
week10/
├── backend/          # FastAPI 服务
├── frontend/         # 聊天页面
├── data/raw_texts/   # 年报摘录文本（可替换为真实 PDF 解析结果）
├── data/chroma/      # Chroma 持久化目录
├── .env.example
└── README.md
```

## 快速开始

### 1. 配置 API Key（系统环境变量）

密钥从环境变量读取，不要写入 `.env`：

```powershell
# 永久（新开终端生效）
setx DEEPSEEK_API_KEY "你的DeepSeek密钥"
setx DASHSCOPE_API_KEY "你的百炼密钥"

# 或仅当前终端
$env:DEEPSEEK_API_KEY="你的DeepSeek密钥"
$env:DASHSCOPE_API_KEY="你的百炼密钥"
```

其余非敏感配置可复制：

```bash
copy .env.example .env
```

### 2. 安装依赖

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 构建知识库索引

```bash
# 仍在 backend 目录、已激活 venv
python -m scripts.ingest --reset
```

### 4. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

浏览器打开：<http://127.0.0.1:8000>

## 可选：真实年报 PDF

1. 编辑 `data/report_manifest.json`（首次运行 `python -m scripts.download_reports` 会生成）填入 PDF 直链  
2. `python -m scripts.download_reports`  
3. `python -m scripts.pdf_to_text`  
4. `python -m scripts.ingest --reset`

## API

- `GET /api/health` — 健康检查与知识库条数  
- `POST /api/chat` — `{ "message": "贵州茅台2023年营业收入是多少？" }`

## 路由逻辑

| 意图 | 行为 |
|------|------|
| 白名单公司年报问题 | Embedding → Chroma → DeepSeek（带引用） |
| 其他公司年报 | 直接返回「暂无相关知识」 |
| 闲聊/通用 | 直接 DeepSeek |

## 验收示例

- `贵州茅台2023年营业收入是多少？` → RAG  
- `洋河股份2023年报净利润？` → 暂无相关知识  
- `用一句话介绍酱香型白酒` → 通用大模型
