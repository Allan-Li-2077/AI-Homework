from fastapi import APIRouter, HTTPException

from app.api.schemas import ChatRequest, ChatResponse, CitationOut
from app.services import chroma_store
from app.services.intent import classify_intent
from app.services.rag import handle_question

router = APIRouter()


@router.get("/health")
def health():
    from app.config import settings

    return {
        "status": "ok",
        "kb_documents": chroma_store.collection_count(),
        "deepseek_configured": settings.has_deepseek(),
        "dashscope_configured": settings.has_dashscope(),
    }


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    question = req.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="message 不能为空")

    try:
        intent = classify_intent(question)
        result = handle_question(question, intent)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"处理失败: {exc}") from exc

    return ChatResponse(
        answer=result.answer,
        mode=result.mode,
        intent=result.intent,
        companies=result.companies,
        citations=[
            CitationOut(
                company=c.company,
                year=c.year,
                page=c.page,
                snippet=c.snippet,
                score=c.score,
            )
            for c in result.citations
        ],
    )
