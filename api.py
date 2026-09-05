"""FastAPI interface for the Evidence RAG Assistant."""

from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from evidence_rag import EvidenceAssistant
from evidence_rag.admin_api import create_admin_router
from evidence_rag.admin_service import AdminService
from evidence_rag.admin_store import AdminStore
from evidence_rag.generation import generate_with_openai
from evidence_rag.observability import (
    DOCUMENT_DOWNLOAD_EVENTS,
    QUERIES_BY_SOURCE,
    RAG_DURATION,
    RAG_QUERIES,
    install_observability,
)

ROOT = Path(__file__).parent


class TelegramUserRequest(BaseModel):
    telegram_id: int = Field(gt=0)
    username: str | None = Field(default=None, max_length=64)
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)


class QuestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    top_k: int | None = Field(default=None, ge=1, le=20)
    use_openai: bool = False
    source: Literal["api", "web", "telegram"] = "api"
    telegram_user: TelegramUserRequest | None = None

    @model_validator(mode="after")
    def require_telegram_identity(self) -> QuestionRequest:
        if self.source == "telegram" and self.telegram_user is None:
            raise ValueError("telegram_user is required when source is telegram")
        return self


class DocumentDownloadRequest(BaseModel):
    telegram_user: TelegramUserRequest
    document_name: str = Field(min_length=1, max_length=200)
    telegram_file_id: str | None = Field(default=None, max_length=300)


class Citation(BaseModel):
    source: str
    section: str
    score: float


class AnswerResponse(BaseModel):
    query_id: int
    answer: str
    mode: str
    citations: list[Citation]


def create_app(*, database_path: Path | None = None, knowledge_dir: Path | None = None) -> FastAPI:
    knowledge_path = knowledge_dir or ROOT / "knowledge"
    database = database_path or Path(os.getenv("HUJJAT_DATABASE_PATH", ROOT / "data" / "admin.db"))
    admin = AdminService(AdminStore(database), knowledge_path)
    admin.sync_documents()

    def configured_generator(question, results):
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required for generated answers")
        settings = {item["key"]: item["value"] for item in admin.get_settings()}
        return generate_with_openai(
            question,
            results,
            model=settings["openai_model"],
            instruction=settings["system_prompt"],
        )

    assistant = EvidenceAssistant(knowledge_path, generator=configured_generator)

    bootstrap_email = os.getenv("HUJJAT_ADMIN_EMAIL")
    bootstrap_password = os.getenv("HUJJAT_ADMIN_PASSWORD")
    if bootstrap_email and bootstrap_password:
        admin.bootstrap_superadmin(bootstrap_email, bootstrap_password)

    application = FastAPI(title="Hujjat AI API", version="0.2.0")
    application.state.assistant = assistant
    application.state.admin = admin
    application.include_router(create_admin_router(admin, assistant.reindex))
    install_observability(application, admin)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/ask", response_model=AnswerResponse)
    def ask(request: QuestionRequest) -> AnswerResponse:
        started = perf_counter()
        telegram_user = request.telegram_user.model_dump() if request.telegram_user else None
        source = "telegram" if telegram_user else request.source
        settings = {item["key"]: item["value"] for item in admin.get_settings()}
        top_k = request.top_k or int(settings["default_top_k"])
        try:
            answer = assistant.ask(request.question, top_k, request.use_openai)
        except ValueError as error:
            duration = perf_counter() - started
            admin.record_query(
                request.question,
                None,
                None,
                [],
                round(duration * 1000),
                error=str(error),
                source=source,
                telegram_user=telegram_user,
            )
            RAG_QUERIES.labels("unknown", "error").inc()
            QUERIES_BY_SOURCE.labels(source, "error").inc()
            RAG_DURATION.observe(duration)
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:
            duration = perf_counter() - started
            admin.record_query(
                request.question,
                None,
                None,
                [],
                round(duration * 1000),
                error=f"{type(error).__name__}: {error}",
                source=source,
                telegram_user=telegram_user,
            )
            RAG_QUERIES.labels("unknown", "error").inc()
            QUERIES_BY_SOURCE.labels(source, "error").inc()
            RAG_DURATION.observe(duration)
            raise HTTPException(status_code=500, detail="Answer generation failed") from error
        duration = perf_counter() - started
        query_id = admin.record_query(
            request.question,
            answer.text,
            answer.mode,
            answer.citations,
            round(duration * 1000),
            source=source,
            telegram_user=telegram_user,
        )
        RAG_QUERIES.labels(answer.mode, "success").inc()
        QUERIES_BY_SOURCE.labels(source, "success").inc()
        RAG_DURATION.observe(duration)
        return AnswerResponse(
            query_id=query_id,
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

    @application.post("/events/document-download", status_code=201)
    def document_download(request: DocumentDownloadRequest) -> dict[str, int]:
        result = admin.record_document_download(
            request.telegram_user.model_dump(),
            request.document_name,
            request.telegram_file_id,
        )
        DOCUMENT_DOWNLOAD_EVENTS.inc()
        return {"download_id": int(result["id"])}

    return application


app = create_app()
