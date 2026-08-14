from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api.chat import router as chat_router
from app.config import settings

app = FastAPI(title="白酒年报智能客服", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@app.get("/")
def index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "前端未找到，请打开 frontend/index.html 或访问 /api/health"}


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def run():
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    run()
