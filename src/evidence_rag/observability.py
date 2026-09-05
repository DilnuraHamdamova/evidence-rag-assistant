"""Prometheus metrics and privacy-safe structured request logging."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from .admin_service import AdminService

HTTP_REQUESTS = Counter(
    "hujjat_http_requests_total",
    "HTTP requests processed by Hujjat AI",
    ("method", "endpoint", "status_code"),
)
HTTP_DURATION = Histogram(
    "hujjat_http_request_duration_seconds",
    "HTTP request latency",
    ("method", "endpoint"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
RAG_QUERIES = Counter(
    "hujjat_rag_queries_total",
    "RAG questions by answer mode and outcome",
    ("mode", "status"),
)
RAG_DURATION = Histogram(
    "hujjat_rag_query_duration_seconds",
    "End-to-end RAG question latency",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
FEEDBACK = Counter(
    "hujjat_feedback_total",
    "Recorded answer feedback",
    ("rating",),
)
REINDEXES = Counter(
    "hujjat_reindexes_total",
    "Knowledge base re-index operations",
    ("status",),
)
QUERIES_BY_SOURCE = Counter(
    "hujjat_queries_by_source_total",
    "Questions by client source and outcome",
    ("source", "status"),
)
DOCUMENT_DOWNLOAD_EVENTS = Counter(
    "hujjat_document_download_events_total",
    "Document downloads reported by bot clients",
)
DOCUMENTS = Gauge("hujjat_documents", "Documents currently registered")
ADMIN_USERS = Gauge("hujjat_admin_users", "Active admin users")
TELEGRAM_USERS = Gauge("hujjat_telegram_users", "Telegram users seen by Hujjat AI")
STORED_DOWNLOADS = Gauge("hujjat_stored_document_downloads", "Stored document downloads")
STORED_QUERIES = Gauge("hujjat_stored_queries", "Questions stored in query history")
STORED_ERRORS = Gauge("hujjat_stored_errors", "Failed questions stored in query history")
POSITIVE_FEEDBACK = Gauge("hujjat_positive_feedback", "Positive feedback records")
NEGATIVE_FEEDBACK = Gauge("hujjat_negative_feedback", "Negative feedback records")

logger = logging.getLogger("hujjat.requests")


def refresh_business_metrics(admin: AdminService) -> None:
    counts = admin.dashboard()["counts"]
    DOCUMENTS.set(counts["documents"])
    ADMIN_USERS.set(counts["users"])
    TELEGRAM_USERS.set(counts["telegram_users"])
    STORED_DOWNLOADS.set(counts["document_downloads"])
    STORED_QUERIES.set(counts["queries"])
    STORED_ERRORS.set(counts["errors"])
    POSITIVE_FEEDBACK.set(counts["positive_feedback"])
    NEGATIVE_FEEDBACK.set(counts["negative_feedback"])


def install_observability(application: FastAPI, admin: AdminService) -> None:
    """Install one middleware and a Prometheus scrape endpoint."""

    @application.middleware("http")
    async def observe_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = perf_counter() - started
            route = request.scope.get("route")
            endpoint = getattr(route, "path", request.url.path)
            HTTP_REQUESTS.labels(request.method, endpoint, str(status_code)).inc()
            HTTP_DURATION.labels(request.method, endpoint).observe(duration)
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "method": request.method,
                        "endpoint": endpoint,
                        "status_code": status_code,
                        "duration_ms": round(duration * 1000, 2),
                    }
                )
            )

    @application.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        refresh_business_metrics(admin)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
