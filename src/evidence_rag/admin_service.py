"""Business rules for authentication and Hujjat AI administration."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .admin_store import AdminStore, utc_now

ROLES = ("viewer", "editor", "admin", "superadmin")
ROLE_LEVEL = {role: index for index, role in enumerate(ROLES)}
ALLOWED_EXTENSIONS = {".md", ".txt"}


class AdminError(ValueError):
    pass


class PermissionDenied(AdminError):
    pass


def password_hash(password: str) -> str:
    if len(password) < 8:
        raise AdminError("Password must contain at least 8 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, expected_hex = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise AdminError("Name must contain letters or numbers")
    return slug


class AdminService:
    def __init__(self, store: AdminStore, knowledge_dir: Path):
        self.store = store
        self.knowledge_dir = knowledge_dir
        knowledge_dir.mkdir(parents=True, exist_ok=True)

    def require_role(self, user: dict[str, Any], minimum: str) -> None:
        if not user.get("is_active") or ROLE_LEVEL[user["role"]] < ROLE_LEVEL[minimum]:
            raise PermissionDenied(f"{minimum} role is required")

    def bootstrap_superadmin(
        self, email: str, password: str, full_name: str = "Super Admin"
    ) -> int:
        existing = self.store.one("SELECT id FROM users LIMIT 1")
        if existing:
            return int(existing["id"])
        return self.create_user(None, email, full_name, password, "superadmin", bootstrap=True)[
            "id"
        ]

    def create_user(
        self,
        actor: dict[str, Any] | None,
        email: str,
        full_name: str,
        password: str,
        role: str,
        *,
        bootstrap: bool = False,
    ) -> dict[str, Any]:
        if not bootstrap:
            if actor is None:
                raise PermissionDenied("Authentication is required")
            self.require_role(actor, "admin")
            if role == "superadmin" and actor["role"] != "superadmin":
                raise PermissionDenied("Only a superadmin can create another superadmin")
        if role not in ROLES:
            raise AdminError("Invalid role")
        normalized_email = email.strip().lower()
        if "@" not in normalized_email:
            raise AdminError("A valid email is required")
        now = utc_now()
        try:
            user_id = self.store.execute(
                """INSERT INTO users
                   (email, full_name, password_hash, role, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (normalized_email, full_name.strip(), password_hash(password), role, now, now),
            )
        except Exception as error:
            if "UNIQUE" in str(error):
                raise AdminError("A user with this email already exists") from error
            raise
        self.store.audit(
            actor["id"] if actor else user_id, "create", "user", user_id, {"role": role}
        )
        return self.get_user(user_id)

    def get_user(self, user_id: int) -> dict[str, Any]:
        user = self.store.one(
            """SELECT id, email, full_name, role, is_active, created_at, updated_at,
                      last_login_at FROM users WHERE id = ?""",
            (user_id,),
        )
        if not user:
            raise AdminError("User not found")
        user["is_active"] = bool(user["is_active"])
        return user

    def list_users(self, actor: dict[str, Any]) -> list[dict[str, Any]]:
        self.require_role(actor, "admin")
        return [
            {**row, "is_active": bool(row["is_active"])}
            for row in self.store.all(
                """SELECT id, email, full_name, role, is_active, created_at, updated_at,
                          last_login_at FROM users ORDER BY created_at DESC"""
            )
        ]

    def update_user(
        self, actor: dict[str, Any], user_id: int, role: str, is_active: bool
    ) -> dict[str, Any]:
        self.require_role(actor, "admin")
        target = self.get_user(user_id)
        if target["role"] == "superadmin" and actor["role"] != "superadmin":
            raise PermissionDenied("Only a superadmin can modify a superadmin")
        if role == "superadmin" and actor["role"] != "superadmin":
            raise PermissionDenied("Only a superadmin can grant that role")
        if role not in ROLES:
            raise AdminError("Invalid role")
        if actor["id"] == user_id and not is_active:
            raise AdminError("You cannot deactivate your own account")
        self.store.execute(
            "UPDATE users SET role = ?, is_active = ?, updated_at = ? WHERE id = ?",
            (role, int(is_active), utc_now(), user_id),
        )
        self.store.audit(
            actor["id"], "update", "user", user_id, {"role": role, "is_active": is_active}
        )
        return self.get_user(user_id)

    def login(self, email: str, password: str, hours: int = 12) -> tuple[str, dict[str, Any]]:
        record = self.store.one("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
        if (
            not record
            or not record["is_active"]
            or not password_matches(password, record["password_hash"])
        ):
            raise PermissionDenied("Invalid email or password")
        token = secrets.token_urlsafe(32)
        token_digest = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now(UTC)
        self.store.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (
                token_digest,
                record["id"],
                (now + timedelta(hours=hours)).isoformat(),
                now.isoformat(),
            ),
        )
        self.store.execute(
            "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now.isoformat(), now.isoformat(), record["id"]),
        )
        self.store.audit(record["id"], "login", "session")
        return token, self.get_user(record["id"])

    def authenticate(self, token: str) -> dict[str, Any]:
        token_digest = hashlib.sha256(token.encode()).hexdigest()
        row = self.store.one(
            """SELECT u.id, u.email, u.full_name, u.role, u.is_active, s.expires_at
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ?""",
            (token_digest,),
        )
        if not row or not row["is_active"]:
            raise PermissionDenied("Invalid session")
        if datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
            self.store.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest,))
            raise PermissionDenied("Session expired")
        return {key: value for key, value in row.items() if key != "expires_at"}

    def logout(self, token: str, actor: dict[str, Any]) -> None:
        self.store.execute(
            "DELETE FROM sessions WHERE token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )
        self.store.audit(actor["id"], "logout", "session")

    def sync_documents(self) -> None:
        now = utc_now()
        for path in sorted((*self.knowledge_dir.glob("*.md"), *self.knowledge_dir.glob("*.txt"))):
            self.store.execute(
                """INSERT INTO documents(title, filename, status, size_bytes, created_at, updated_at)
                   VALUES (?, ?, 'indexed', ?, ?, ?)
                   ON CONFLICT(filename) DO UPDATE SET size_bytes = excluded.size_bytes""",
                (path.stem.replace("_", " ").title(), path.name, path.stat().st_size, now, now),
            )

    def list_documents(self) -> list[dict[str, Any]]:
        self.sync_documents()
        return self.store.all(
            """SELECT d.*, c.name AS category_name, u.full_name AS created_by_name
               FROM documents d
               LEFT JOIN categories c ON c.id = d.category_id
               LEFT JOIN users u ON u.id = d.created_by
               ORDER BY d.updated_at DESC"""
        )

    def _safe_document_path(self, filename: str) -> Path:
        clean_name = Path(filename).name
        if clean_name != filename or Path(clean_name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise AdminError("Only a plain .md or .txt filename is allowed")
        return self.knowledge_dir / clean_name

    def save_document(
        self,
        actor: dict[str, Any],
        title: str,
        filename: str,
        content: str,
        category_id: int | None = None,
    ) -> dict[str, Any]:
        self.require_role(actor, "editor")
        path = self._safe_document_path(filename)
        if not content.strip():
            raise AdminError("Document content cannot be empty")
        if category_id and not self.store.one(
            "SELECT id FROM categories WHERE id = ?", (category_id,)
        ):
            raise AdminError("Category not found")
        existed = path.exists()
        path.write_text(content, encoding="utf-8")
        now = utc_now()
        self.store.execute(
            """INSERT INTO documents
               (title, filename, category_id, status, size_bytes, created_by, created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
               ON CONFLICT(filename) DO UPDATE SET title = excluded.title,
                   category_id = excluded.category_id, status = 'pending',
                   size_bytes = excluded.size_bytes, updated_at = excluded.updated_at""",
            (title.strip(), filename, category_id, path.stat().st_size, actor["id"], now, now),
        )
        document = self.store.one("SELECT * FROM documents WHERE filename = ?", (filename,))
        assert document
        self.store.audit(
            actor["id"],
            "update" if existed else "create",
            "document",
            document["id"],
            {"filename": filename},
        )
        return document

    def document_content(self, document_id: int) -> str:
        document = self.store.one("SELECT filename FROM documents WHERE id = ?", (document_id,))
        if not document:
            raise AdminError("Document not found")
        path = self._safe_document_path(document["filename"])
        if not path.exists():
            raise AdminError("Document file is missing")
        return path.read_text(encoding="utf-8")

    def delete_document(self, actor: dict[str, Any], document_id: int) -> None:
        self.require_role(actor, "editor")
        document = self.store.one("SELECT * FROM documents WHERE id = ?", (document_id,))
        if not document:
            raise AdminError("Document not found")
        path = self._safe_document_path(document["filename"])
        if path.exists():
            path.unlink()
        self.store.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        self.store.audit(
            actor["id"], "delete", "document", document_id, {"filename": document["filename"]}
        )

    def mark_documents_indexed(self, actor: dict[str, Any]) -> None:
        self.require_role(actor, "editor")
        self.store.execute("UPDATE documents SET status = 'indexed', updated_at = ?", (utc_now(),))
        self.store.audit(actor["id"], "reindex", "knowledge_base")

    def list_categories(self) -> list[dict[str, Any]]:
        return self.store.all(
            """SELECT c.*, COUNT(d.id) AS document_count FROM categories c
               LEFT JOIN documents d ON d.category_id = c.id
               GROUP BY c.id ORDER BY c.name"""
        )

    def save_category(
        self,
        actor: dict[str, Any],
        name: str,
        description: str = "",
        category_id: int | None = None,
    ) -> dict[str, Any]:
        self.require_role(actor, "editor")
        now = utc_now()
        try:
            if category_id:
                self.store.execute(
                    "UPDATE categories SET name = ?, slug = ?, description = ?, updated_at = ? WHERE id = ?",
                    (name.strip(), slugify(name), description.strip(), now, category_id),
                )
                action = "update"
            else:
                category_id = self.store.execute(
                    """INSERT INTO categories(name, slug, description, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (name.strip(), slugify(name), description.strip(), now, now),
                )
                action = "create"
        except Exception as error:
            if "UNIQUE" in str(error):
                raise AdminError("A category with this name already exists") from error
            raise
        self.store.audit(actor["id"], action, "category", category_id)
        category = self.store.one("SELECT * FROM categories WHERE id = ?", (category_id,))
        assert category
        return category

    def delete_category(self, actor: dict[str, Any], category_id: int) -> None:
        self.require_role(actor, "editor")
        if not self.store.one("SELECT id FROM categories WHERE id = ?", (category_id,)):
            raise AdminError("Category not found")
        self.store.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        self.store.audit(actor["id"], "delete", "category", category_id)

    def record_query(
        self,
        question: str,
        answer: str | None,
        mode: str | None,
        citations: list[str],
        latency_ms: int,
        *,
        error: str | None = None,
    ) -> int:
        return self.store.execute(
            """INSERT INTO query_history
               (question, answer, mode, citations_json, latency_ms, status, error, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                question,
                answer,
                mode,
                json.dumps(citations, ensure_ascii=False),
                latency_ms,
                "error" if error else "success",
                error,
                utc_now(),
            ),
        )

    def list_queries(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.store.all("SELECT * FROM query_history ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["citations"] = json.loads(row.pop("citations_json"))
        return rows

    def add_feedback(
        self, actor: dict[str, Any] | None, query_id: int, rating: int, comment: str = ""
    ) -> dict[str, Any]:
        if actor is not None:
            self.require_role(actor, "editor")
        if rating not in (-1, 1):
            raise AdminError("Rating must be 1 or -1")
        if not self.store.one("SELECT id FROM query_history WHERE id = ?", (query_id,)):
            raise AdminError("Query not found")
        feedback_id = self.store.execute(
            "INSERT INTO feedback(query_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
            (query_id, rating, comment.strip(), utc_now()),
        )
        self.store.audit(
            actor["id"] if actor else None,
            "create",
            "feedback",
            feedback_id,
            {"query_id": query_id},
        )
        feedback = self.store.one("SELECT * FROM feedback WHERE id = ?", (feedback_id,))
        assert feedback
        return feedback

    def list_feedback(self) -> list[dict[str, Any]]:
        return self.store.all(
            """SELECT f.*, q.question FROM feedback f JOIN query_history q ON q.id = f.query_id
               ORDER BY f.id DESC"""
        )

    def get_settings(self) -> list[dict[str, Any]]:
        return self.store.all("SELECT * FROM settings ORDER BY key")

    def update_setting(self, actor: dict[str, Any], key: str, value: str) -> dict[str, Any]:
        self.require_role(actor, "admin")
        if key not in {"openai_model", "default_top_k", "system_prompt"}:
            raise AdminError("Unknown setting")
        if key == "default_top_k" and (not value.isdigit() or not 1 <= int(value) <= 20):
            raise AdminError("default_top_k must be between 1 and 20")
        self.store.execute(
            "UPDATE settings SET value = ?, updated_by = ?, updated_at = ? WHERE key = ?",
            (value.strip(), actor["id"], utc_now(), key),
        )
        self.store.audit(actor["id"], "update", "setting", key, {"value": value})
        setting = self.store.one("SELECT * FROM settings WHERE key = ?", (key,))
        assert setting
        return setting

    def dashboard(self) -> dict[str, Any]:
        self.sync_documents()
        counts = self.store.one(
            """SELECT
                (SELECT COUNT(*) FROM documents) AS documents,
                (SELECT COUNT(*) FROM categories) AS categories,
                (SELECT COUNT(*) FROM users WHERE is_active = 1) AS users,
                (SELECT COUNT(*) FROM query_history) AS queries,
                (SELECT COUNT(*) FROM query_history WHERE status = 'error') AS errors,
                (SELECT COUNT(*) FROM feedback WHERE rating = 1) AS positive_feedback,
                (SELECT COUNT(*) FROM feedback WHERE rating = -1) AS negative_feedback"""
        )
        assert counts
        recent = self.store.all(
            "SELECT id, question, mode, status, latency_ms, created_at FROM query_history ORDER BY id DESC LIMIT 10"
        )
        return {"counts": counts, "recent_queries": recent}

    def audit_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.store.all(
            """SELECT a.*, u.email AS actor_email FROM audit_logs a
               LEFT JOIN users u ON u.id = a.actor_id ORDER BY a.id DESC LIMIT ?""",
            (limit,),
        )
        for row in rows:
            row["details"] = json.loads(row.pop("details_json"))
        return rows
