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


def test_users_feedback_settings_and_audit_endpoints(admin_app):
    client = TestClient(admin_app)
    headers = login(client)

    created_user = client.post(
        "/admin/users",
        headers=headers,
        json={
            "email": "editor@example.com",
            "full_name": "Content Editor",
            "password": "editor-password",
            "role": "editor",
        },
    )
    assert created_user.status_code == 200
    assert created_user.json()["role"] == "editor"
    assert len(client.get("/admin/users", headers=headers).json()) == 2

    answer = client.post("/ask", json={"question": "What does the policy require?"}).json()
    feedback = client.post(
        "/feedback", json={"query_id": answer["query_id"], "rating": 1, "comment": "Useful"}
    )
    assert feedback.status_code == 200
    assert client.get("/admin/feedback", headers=headers).json()[0]["rating"] == 1

    updated_setting = client.put(
        "/admin/settings/default_top_k", headers=headers, json={"value": "5"}
    )
    assert updated_setting.status_code == 200
    assert updated_setting.json()["value"] == "5"

    audit_logs = client.get("/admin/audit-logs", headers=headers)
    assert audit_logs.status_code == 200
    assert {item["entity_type"] for item in audit_logs.json()} >= {
        "user",
        "feedback",
        "setting",
    }


def test_viewer_has_read_only_admin_access(admin_app):
    service = admin_app.state.admin
    owner = service.get_user(1)
    service.create_user(owner, "viewer@example.com", "Viewer", "viewer-password", "viewer")
    client = TestClient(admin_app)
    login_response = client.post(
        "/auth/login", json={"email": "viewer@example.com", "password": "viewer-password"}
    )
    viewer_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    assert client.get("/admin/dashboard", headers=viewer_headers).status_code == 200
    assert client.get("/admin/documents", headers=viewer_headers).status_code == 200
    assert (
        client.post(
            "/admin/categories",
            headers=viewer_headers,
            json={"name": "Forbidden", "description": ""},
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/admin/settings/default_top_k",
            headers=viewer_headers,
            json={"value": "4"},
        ).status_code
        == 403
    )


def test_telegram_user_questions_feedback_and_downloads_are_tracked(admin_app):
    client = TestClient(admin_app)
    headers = login(client)
    telegram_user = {
        "telegram_id": 123456789,
        "username": "dilnura_test",
        "first_name": "Dilnura",
        "last_name": "Hamdamova",
    }

    answer = client.post(
        "/ask",
        json={
            "question": "What audit trail is needed?",
            "source": "telegram",
            "telegram_user": telegram_user,
        },
    )
    assert answer.status_code == 200
    query_id = answer.json()["query_id"]

    feedback = client.post(
        "/feedback",
        json={"query_id": query_id, "rating": -1, "comment": "Wrong answer"},
    )
    assert feedback.status_code == 200
    download = client.post(
        "/events/document-download",
        json={"telegram_user": telegram_user, "document_name": "base.md"},
    )
    assert download.status_code == 201

    users = client.get("/admin/telegram-users", headers=headers).json()
    assert len(users) == 1
    assert users[0]["username"] == "dilnura_test"
    assert users[0]["query_count"] == 1
    assert users[0]["negative_feedback"] == 1
    assert users[0]["download_count"] == 1

    details = client.get(f"/admin/telegram-users/{users[0]['id']}", headers=headers).json()
    assert details["queries"][0]["feedback_rating"] == -1
    assert details["downloads"][0]["document_name"] == "base.md"

    query = client.get("/admin/queries", headers=headers).json()[0]
    assert query["source"] == "telegram"
    assert query["telegram_username"] == "dilnura_test"

    dashboard = client.get("/admin/dashboard", headers=headers).json()
    assert dashboard["counts"]["telegram_users"] == 1
    assert dashboard["counts"]["document_downloads"] == 1


def test_unexpected_bot_failure_is_visible_in_user_history(admin_app, monkeypatch):
    client = TestClient(admin_app)

    def fail(*args, **kwargs):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(admin_app.state.assistant, "ask", fail)
    response = client.post(
        "/ask",
        json={
            "question": "This request should fail",
            "source": "telegram",
            "telegram_user": {"telegram_id": 987654321, "username": "failed_user"},
        },
    )
    assert response.status_code == 500
    history = admin_app.state.admin.list_queries()
    assert history[0]["status"] == "error"
    assert history[0]["telegram_username"] == "failed_user"
    assert "provider timeout" in history[0]["error"]


def test_telegram_source_requires_user_identity(admin_app):
    client = TestClient(admin_app)
    response = client.post(
        "/ask",
        json={"question": "Who asked this?", "source": "telegram"},
    )
    assert response.status_code == 422
