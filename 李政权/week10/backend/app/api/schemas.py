from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None


class CitationOut(BaseModel):
    company: str
    year: str | int
    page: str | int
    snippet: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    mode: str
    intent: str = ""
    companies: list[str] = []
    citations: list[CitationOut] = []
