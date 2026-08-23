"""FastAPI interface for the Evidence RAG Assistant."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from evidence_rag import EvidenceAssistant

assistant = EvidenceAssistant(Path(__file__).parent / "knowledge")
app = FastAPI(title="Evidence RAG Assistant API", version="0.1.0")


class QuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    top_k: int = Field(default=3, ge=1, le=5)
    use_openai: bool = False


class Citation(BaseModel):
    source: str
    section: str
    score: float


class AnswerResponse(BaseModel):
    answer: str
    mode: str
    citations: list[Citation]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=AnswerResponse)
def ask(request: QuestionRequest) -> AnswerResponse:
    try:
        answer = assistant.ask(request.question, request.top_k, request.use_openai)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return AnswerResponse(
        answer=answer.text,
        mode=answer.mode,
        citations=[
            Citation(
                source=item.chunk.source,
                section=item.chunk.section,
                score=round(item.score, 4),
            )
            for item in answer.results
        ],
    )

