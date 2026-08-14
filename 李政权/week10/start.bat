@echo off
cd /d "%~dp0backend"
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
echo [1/2] 构建/刷新知识库索引...
.venv\Scripts\python -m scripts.ingest --reset
echo [2/2] 启动服务 http://127.0.0.1:8000
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pause
