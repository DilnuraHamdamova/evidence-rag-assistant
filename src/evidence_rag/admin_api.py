"""FastAPI routes for the Hujjat AI administration panel."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .admin_service import AdminError, AdminService, PermissionDenied
from .observability import FEEDBACK, REINDEXES


class LoginRequest(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    email: str
    full_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    role: str = "viewer"


class UserUpdate(BaseModel):
    role: str
    is_active: bool


class DocumentWrite(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=3, max_length=150)
    content: str = Field(min_length=1, max_length=2_000_000)
    category_id: int | None = None


class CategoryWrite(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class FeedbackCreate(BaseModel):
    query_id: int
    rating: int
    comment: str = Field(default="", max_length=1000)


class SettingWrite(BaseModel):
    value: str = Field(max_length=10_000)


def create_admin_router(service: AdminService, reindex: Callable[[], int]) -> APIRouter:
    router = APIRouter()
    security = HTTPBearer(auto_error=False)

    def current_token(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> str:
        if not credentials or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Authentication required")
        return credentials.credentials

    def current_user(token: Annotated[str, Depends(current_token)]) -> dict[str, Any]:
        try:
            return service.authenticate(token)
        except PermissionDenied as error:
            raise HTTPException(status_code=401, detail=str(error)) from error

    def handle(error: AdminError) -> HTTPException:
        status = 403 if isinstance(error, PermissionDenied) else 400
        return HTTPException(status_code=status, detail=str(error))

    @router.post("/auth/login")
    def login(request: LoginRequest) -> dict[str, Any]:
        try:
            token, user = service.login(request.email, request.password)
            return {"access_token": token, "token_type": "bearer", "user": user}
        except AdminError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error

    @router.post("/auth/logout", status_code=204)
    def logout(
        token: Annotated[str, Depends(current_token)],
        user: Annotated[dict[str, Any], Depends(current_user)],
    ) -> None:
        service.logout(token, user)

    @router.get("/auth/me")
    def me(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        return user

    @router.get("/admin/dashboard")
    def dashboard(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        return service.dashboard()

    @router.get("/admin/documents")
    def documents(user: Annotated[dict[str, Any], Depends(current_user)]) -> list[dict[str, Any]]:
        return service.list_documents()

    @router.get("/admin/documents/{document_id}/content")
    def document_content(
        document_id: int, user: Annotated[dict[str, Any], Depends(current_user)]
    ) -> dict[str, str]:
        try:
            return {"content": service.document_content(document_id)}
        except AdminError as error:
            raise handle(error) from error

    @router.post("/admin/documents")
    def save_document(
        request: DocumentWrite, user: Annotated[dict[str, Any], Depends(current_user)]
    ) -> dict[str, Any]:
        try:
            return service.save_document(
                user, request.title, request.filename, request.content, request.category_id
            )
        except AdminError as error:
            raise handle(error) from error

    @router.delete("/admin/documents/{document_id}", status_code=204)
    def delete_document(
        document_id: int, user: Annotated[dict[str, Any], Depends(current_user)]
    ) -> None:
        try:
            service.delete_document(user, document_id)
            reindex()
        except AdminError as error:
            raise handle(error) from error

    @router.post("/admin/documents/reindex")
    def rebuild_index(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, int]:
        try:
            service.require_role(user, "editor")
            chunk_count = reindex()
            service.mark_documents_indexed(user)
            REINDEXES.labels("success").inc()
            return {"chunks": chunk_count}
        except AdminError as error:
            REINDEXES.labels("error").inc()
            raise handle(error) from error

    @router.get("/admin/categories")
    def categories(user: Annotated[dict[str, Any], Depends(current_user)]) -> list[dict[str, Any]]:
        return service.list_categories()

    @router.post("/admin/categories")
    def create_category(
        request: CategoryWrite, user: Annotated[dict[str, Any], Depends(current_user)]
    ) -> dict[str, Any]:
        try:
            return service.save_category(user, request.name, request.description)
        except AdminError as error:
            raise handle(error) from error

    @router.put("/admin/categories/{category_id}")
    def update_category(
        category_id: int,
        request: CategoryWrite,
        user: Annotated[dict[str, Any], Depends(current_user)],
    ) -> dict[str, Any]:
        try:
            return service.save_category(user, request.name, request.description, category_id)
        except AdminError as error:
            raise handle(error) from error

    @router.delete("/admin/categories/{category_id}", status_code=204)
    def delete_category(
        category_id: int, user: Annotated[dict[str, Any], Depends(current_user)]
    ) -> None:
        try:
            service.delete_category(user, category_id)
        except AdminError as error:
            raise handle(error) from error

    @router.get("/admin/users")
    def users(user: Annotated[dict[str, Any], Depends(current_user)]) -> list[dict[str, Any]]:
        try:
            return service.list_users(user)
        except AdminError as error:
            raise handle(error) from error

    @router.post("/admin/users")
    def create_user(
        request: UserCreate, user: Annotated[dict[str, Any], Depends(current_user)]
    ) -> dict[str, Any]:
        try:
            return service.create_user(
                user, request.email, request.full_name, request.password, request.role
            )
        except AdminError as error:
            raise handle(error) from error

    @router.patch("/admin/users/{user_id}")
    def update_user(
        user_id: int,
        request: UserUpdate,
        user: Annotated[dict[str, Any], Depends(current_user)],
    ) -> dict[str, Any]:
        try:
            return service.update_user(user, user_id, request.role, request.is_active)
        except AdminError as error:
            raise handle(error) from error

    @router.get("/admin/telegram-users")
    def telegram_users(
        user: Annotated[dict[str, Any], Depends(current_user)],
    ) -> list[dict[str, Any]]:
        return service.list_telegram_users()

    @router.get("/admin/telegram-users/{telegram_user_id}")
    def telegram_user_details(
        telegram_user_id: int,
        user: Annotated[dict[str, Any], Depends(current_user)],
    ) -> dict[str, Any]:
        try:
            return service.telegram_user_details(telegram_user_id)
        except AdminError as error:
            raise handle(error) from error

    @router.get("/admin/document-downloads")
    def document_downloads(
        user: Annotated[dict[str, Any], Depends(current_user)],
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return service.list_document_downloads(limit)

    @router.get("/admin/queries")
    def queries(
        user: Annotated[dict[str, Any], Depends(current_user)],
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return service.list_queries(limit)

    @router.get("/admin/feedback")
    def feedback(user: Annotated[dict[str, Any], Depends(current_user)]) -> list[dict[str, Any]]:
        return service.list_feedback()

    @router.post("/feedback")
    def public_feedback(request: FeedbackCreate) -> dict[str, Any]:
        try:
            result = service.add_feedback(None, request.query_id, request.rating, request.comment)
            FEEDBACK.labels("positive" if request.rating == 1 else "negative").inc()
            return result
        except AdminError as error:
            raise handle(error) from error

    @router.post("/admin/feedback")
    def add_feedback(
        request: FeedbackCreate, user: Annotated[dict[str, Any], Depends(current_user)]
    ) -> dict[str, Any]:
        try:
            result = service.add_feedback(user, request.query_id, request.rating, request.comment)
            FEEDBACK.labels("positive" if request.rating == 1 else "negative").inc()
            return result
        except AdminError as error:
            raise handle(error) from error

    @router.get("/admin/settings")
    def settings(user: Annotated[dict[str, Any], Depends(current_user)]) -> list[dict[str, Any]]:
        return service.get_settings()

    @router.put("/admin/settings/{key}")
    def update_setting(
        key: str,
        request: SettingWrite,
        user: Annotated[dict[str, Any], Depends(current_user)],
    ) -> dict[str, Any]:
        try:
            return service.update_setting(user, key, request.value)
        except AdminError as error:
            raise handle(error) from error

    @router.get("/admin/audit-logs")
    def audit_logs(
        user: Annotated[dict[str, Any], Depends(current_user)],
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        try:
            service.require_role(user, "admin")
            return service.audit_logs(limit)
        except AdminError as error:
            raise handle(error) from error

    return router
