from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import create_app
from evidence_rag.admin_service import AdminError, PermissionDenied


@pytest.fixture
def admin_app(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "base.md").write_text("# Base\n\n## Policy\n\nKeep a useful audit trail.")
    app = create_app(database_path=tmp_path / "admin.db", knowledge_dir=knowledge)
    app.state.admin.bootstrap_superadmin("owner@example.com", "strong-password")
    return app


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/login", json={"email": "owner@example.com", "password": "strong-password"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_dashboard_and_query_history(admin_app):
    client = TestClient(admin_app)
    headers = login(client)

    answer = client.post("/ask", json={"question": "What audit trail is needed?"})
    assert answer.status_code == 200
    assert answer.json()["query_id"] > 0

    dashboard = client.get("/admin/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["counts"]["queries"] == 1
    assert dashboard.json()["counts"]["documents"] == 1


def test_document_category_and_reindex_workflow(admin_app):
    client = TestClient(admin_app)
    headers = login(client)

    category = client.post(
        "/admin/categories",
        headers=headers,
        json={"name": "Legal", "description": "Legal source documents"},
    )
    assert category.status_code == 200

    document = client.post(
        "/admin/documents",
        headers=headers,
        json={
            "title": "Contract policy",
            "filename": "contracts.md",
            "content": "# Contracts\n\n## Review\n\nA person must review every contract.",
            "category_id": category.json()["id"],
        },
    )
    assert document.status_code == 200
    assert document.json()["status"] == "pending"

    rebuilt = client.post("/admin/documents/reindex", headers=headers)
    assert rebuilt.status_code == 200
    assert rebuilt.json()["chunks"] == 2
    rows = client.get("/admin/documents", headers=headers).json()
    assert next(row for row in rows if row["filename"] == "contracts.md")["status"] == "indexed"


def test_role_permissions_and_audit(admin_app):
    service = admin_app.state.admin
    owner = service.get_user(1)
    viewer = service.create_user(owner, "reader@example.com", "Reader", "reader-password", "viewer")

    with pytest.raises(PermissionDenied):
        service.save_document(viewer, "Unsafe", "unsafe.md", "Not permitted")
    with pytest.raises(AdminError, match="plain .md or .txt"):
        service.save_document(owner, "Traversal", "../outside.md", "Not permitted")

    logs = service.audit_logs()
    assert any(row["action"] == "create" and row["entity_type"] == "user" for row in logs)
