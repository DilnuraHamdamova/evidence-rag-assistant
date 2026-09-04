"""Streamlit administration panel for Hujjat AI."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from evidence_rag import EvidenceAssistant
from evidence_rag.admin_service import ROLE_LEVEL, AdminError, AdminService
from evidence_rag.admin_store import AdminStore

ROOT = Path(__file__).parent


@st.cache_resource
def runtime() -> tuple[AdminService, EvidenceAssistant]:
    knowledge_dir = ROOT / "knowledge"
    database_path = Path(os.getenv("HUJJAT_DATABASE_PATH", ROOT / "data" / "admin.db"))
    service = AdminService(AdminStore(database_path), knowledge_dir)
    service.sync_documents()
    email = os.getenv("HUJJAT_ADMIN_EMAIL")
    password = os.getenv("HUJJAT_ADMIN_PASSWORD")
    if email and password:
        service.bootstrap_superadmin(email, password)
    return service, EvidenceAssistant(knowledge_dir)


admin, assistant = runtime()
st.set_page_config(page_title="Hujjat AI Admin", page_icon="🛡️", layout="wide")


def flash_error(error: Exception) -> None:
    st.error(str(error))


def role_at_least(role: str) -> bool:
    return ROLE_LEVEL[st.session_state.user["role"]] >= ROLE_LEVEL[role]


def login_screen() -> None:
    st.title("🛡️ Hujjat AI Admin")
    st.caption("Boshqaruv paneliga kirish")
    if not admin.store.one("SELECT id FROM users LIMIT 1"):
        st.warning("Birinchi superadmin hali yaratilmagan.")
        st.code(
            "python -m evidence_rag.admin_cli --email admin@example.com",
            language="bash",
        )
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Parol", type="password")
        if st.form_submit_button("Kirish", type="primary", use_container_width=True):
            try:
                token, user = admin.login(email, password)
                st.session_state.token = token
                st.session_state.user = user
                st.rerun()
            except AdminError as error:
                flash_error(error)


def dashboard_page() -> None:
    st.header("Dashboard")
    data = admin.dashboard()
    counts = data["counts"]
    columns = st.columns(5)
    columns[0].metric("Hujjatlar", counts["documents"])
    columns[1].metric("Savollar", counts["queries"])
    columns[2].metric("Foydalanuvchilar", counts["users"])
    columns[3].metric("Xatolar", counts["errors"])
    columns[4].metric(
        "Feedback",
        f"{counts['positive_feedback']} 👍 / {counts['negative_feedback']} 👎",
    )
    st.subheader("Oxirgi savollar")
    if data["recent_queries"]:
        st.dataframe(data["recent_queries"], use_container_width=True, hide_index=True)
    else:
        st.info("Hali savollar yozilmagan.")


def documents_page() -> None:
    st.header("Documents")
    documents = admin.list_documents()
    categories = admin.list_categories()
    if documents:
        st.dataframe(documents, use_container_width=True, hide_index=True)
    if not role_at_least("editor"):
        st.info("Viewer hujjatlarni faqat ko‘ra oladi.")
        return

    category_options = {"Kategoriyasiz": None, **{item["name"]: item["id"] for item in categories}}
    with st.expander("Hujjat qo‘shish yoki yangilash", expanded=not documents):
        uploaded = st.file_uploader("Markdown yoki text fayl", type=["md", "txt"])
        title = st.text_input("Sarlavha")
        category_name = st.selectbox("Kategoriya", list(category_options))
        manual_content = st.text_area("Matn (fayl tanlanmasa)", height=220)
        filename = st.text_input("Fayl nomi", placeholder="example.md")
        if st.button("Saqlash", type="primary"):
            try:
                actual_name = uploaded.name if uploaded else filename
                content = uploaded.getvalue().decode("utf-8") if uploaded else manual_content
                actual_title = title or Path(actual_name).stem.replace("_", " ").title()
                admin.save_document(
                    st.session_state.user,
                    actual_title,
                    actual_name,
                    content,
                    category_options[category_name],
                )
                st.success("Hujjat saqlandi. Endi indeksni yangilang.")
                st.rerun()
            except (AdminError, UnicodeDecodeError) as error:
                flash_error(error)

    if documents:
        selected = st.selectbox(
            "Tahrirlash uchun hujjat",
            documents,
            format_func=lambda item: f"{item['title']} ({item['filename']})",
        )
        with st.expander("Tanlangan hujjatni tahrirlash yoki o‘chirish"):
            try:
                existing_content = admin.document_content(selected["id"])
            except AdminError as error:
                existing_content = ""
                flash_error(error)
            edit_title = st.text_input("Sarlavha ", value=selected["title"])
            edit_content = st.text_area(
                "Matn", value=existing_content, height=300, key="edit_content"
            )
            current_category = next(
                (
                    name
                    for name, category_id in category_options.items()
                    if category_id == selected["category_id"]
                ),
                "Kategoriyasiz",
            )
            edit_category_name = st.selectbox(
                "Kategoriya ",
                list(category_options),
                index=list(category_options).index(current_category),
            )
            col1, col2 = st.columns(2)
            if col1.button("O‘zgarishlarni saqlash"):
                try:
                    admin.save_document(
                        st.session_state.user,
                        edit_title,
                        selected["filename"],
                        edit_content,
                        category_options[edit_category_name],
                    )
                    st.success("O‘zgarish saqlandi.")
                    st.rerun()
                except AdminError as error:
                    flash_error(error)
            confirm = st.checkbox("O‘chirishni tasdiqlayman")
            if col2.button("Hujjatni o‘chirish", disabled=not confirm):
                try:
                    admin.delete_document(st.session_state.user, selected["id"])
                    assistant.reindex()
                    st.success("Hujjat o‘chirildi.")
                    st.rerun()
                except AdminError as error:
                    flash_error(error)

    if st.button("🔄 Barcha hujjatlarni qayta indekslash", type="primary"):
        try:
            chunks = assistant.reindex()
            admin.mark_documents_indexed(st.session_state.user)
            st.success(f"Indeks yangilandi: {chunks} ta chunk.")
            st.rerun()
        except AdminError as error:
            flash_error(error)


def categories_page() -> None:
    st.header("Categories")
    categories = admin.list_categories()
    if categories:
        st.dataframe(categories, use_container_width=True, hide_index=True)
    if not role_at_least("editor"):
        return
    with st.form("category_create"):
        name = st.text_input("Kategoriya nomi")
        description = st.text_area("Izoh")
        if st.form_submit_button("Kategoriya qo‘shish", type="primary"):
            try:
                admin.save_category(st.session_state.user, name, description)
                st.rerun()
            except AdminError as error:
                flash_error(error)
    if categories:
        selected = st.selectbox(
            "Kategoriyani boshqarish", categories, format_func=lambda item: item["name"]
        )
        edit_name = st.text_input("Kategoriya nomi ", value=selected["name"])
        edit_description = st.text_area("Izoh ", value=selected["description"])
        update_column, delete_column = st.columns(2)
        if update_column.button("Kategoriyani yangilash"):
            try:
                admin.save_category(
                    st.session_state.user,
                    edit_name,
                    edit_description,
                    selected["id"],
                )
                st.success("Kategoriya yangilandi.")
                st.rerun()
            except AdminError as error:
                flash_error(error)
        confirm = st.checkbox("Kategoriya o‘chirilishini tasdiqlayman")
        if delete_column.button("Kategoriyani o‘chirish", disabled=not confirm):
            try:
                admin.delete_category(st.session_state.user, selected["id"])
                st.rerun()
            except AdminError as error:
                flash_error(error)


def users_page() -> None:
    st.header("Users & roles")
    users = admin.list_users(st.session_state.user)
    st.dataframe(users, use_container_width=True, hide_index=True)
    with st.form("user_create"):
        st.subheader("Yangi foydalanuvchi")
        email = st.text_input("Email")
        full_name = st.text_input("To‘liq ism")
        password = st.text_input("Vaqtinchalik parol", type="password")
        allowed_roles = ["viewer", "editor", "admin"]
        if st.session_state.user["role"] == "superadmin":
            allowed_roles.append("superadmin")
        role = st.selectbox("Rol", allowed_roles)
        if st.form_submit_button("Foydalanuvchi yaratish", type="primary"):
            try:
                admin.create_user(st.session_state.user, email, full_name, password, role)
                st.rerun()
            except AdminError as error:
                flash_error(error)
    manageable_users = [
        item
        for item in users
        if st.session_state.user["role"] == "superadmin" or item["role"] != "superadmin"
    ]
    selected = st.selectbox(
        "Foydalanuvchini boshqarish", manageable_users, format_func=lambda item: item["email"]
    )
    role = st.selectbox("Yangi rol", allowed_roles, index=allowed_roles.index(selected["role"]))
    active = st.toggle("Faol", value=selected["is_active"])
    if st.button("Foydalanuvchini yangilash"):
        try:
            admin.update_user(st.session_state.user, selected["id"], role, active)
            st.rerun()
        except AdminError as error:
            flash_error(error)


def history_page() -> None:
    st.header("Query history")
    queries = admin.list_queries(500)
    search = st.text_input("Savol bo‘yicha qidirish").strip().lower()
    status = st.selectbox("Holat", ["Barchasi", "success", "error"])
    if search:
        queries = [item for item in queries if search in item["question"].lower()]
    if status != "Barchasi":
        queries = [item for item in queries if item["status"] == status]
    if queries:
        st.dataframe(queries, use_container_width=True, hide_index=True)
    else:
        st.info("Hali query mavjud emas.")


def feedback_page() -> None:
    st.header("Feedback")
    feedback = admin.list_feedback()
    if feedback:
        st.dataframe(feedback, use_container_width=True, hide_index=True)
    queries = admin.list_queries(100)
    if role_at_least("editor") and queries:
        with st.form("feedback_create"):
            query = st.selectbox(
                "Savol",
                queries,
                format_func=lambda item: f"#{item['id']} — {item['question'][:80]}",
            )
            label = st.radio("Baho", ["Foydali 👍", "Foydasiz 👎"], horizontal=True)
            comment = st.text_area("Izoh")
            if st.form_submit_button("Feedback saqlash"):
                try:
                    admin.add_feedback(
                        st.session_state.user,
                        query["id"],
                        1 if label.startswith("Foydali ") else -1,
                        comment,
                    )
                    st.rerun()
                except AdminError as error:
                    flash_error(error)


def settings_page() -> None:
    st.header("Settings")
    for setting in admin.get_settings():
        with st.form(f"setting_{setting['key']}"):
            st.caption(setting["description"])
            value = st.text_area(setting["key"], value=setting["value"])
            if st.form_submit_button("Saqlash", disabled=not role_at_least("admin")):
                try:
                    admin.update_setting(st.session_state.user, setting["key"], value)
                    st.success("Sozlama yangilandi.")
                    st.rerun()
                except AdminError as error:
                    flash_error(error)


def audit_page() -> None:
    st.header("Audit log")
    logs = admin.audit_logs(500)
    actions = ["Barchasi", *sorted({item["action"] for item in logs})]
    action = st.selectbox("Amal bo‘yicha filter", actions)
    if action != "Barchasi":
        logs = [item for item in logs if item["action"] == action]
    st.dataframe(logs, use_container_width=True, hide_index=True)


if "token" not in st.session_state or "user" not in st.session_state:
    login_screen()
    st.stop()

try:
    st.session_state.user = admin.authenticate(st.session_state.token)
except AdminError:
    st.session_state.clear()
    st.rerun()

user = st.session_state.user
with st.sidebar:
    st.title("Hujjat AI")
    st.write(user["full_name"])
    st.caption(f"{user['email']} · {user['role']}")
    pages = ["Dashboard", "Documents", "Categories", "Query history", "Feedback", "Settings"]
    if role_at_least("admin"):
        pages.extend(["Users & roles", "Audit log"])
    selected_page = st.radio("Bo‘lim", pages)
    if st.button("Chiqish", use_container_width=True):
        admin.logout(st.session_state.token, user)
        st.session_state.clear()
        st.rerun()

PAGE_HANDLERS = {
    "Dashboard": dashboard_page,
    "Documents": documents_page,
    "Categories": categories_page,
    "Users & roles": users_page,
    "Query history": history_page,
    "Feedback": feedback_page,
    "Settings": settings_page,
    "Audit log": audit_page,
}
PAGE_HANDLERS[selected_page]()
