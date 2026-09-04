"""Streamlit administration panel for Hujjat AI."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from evidence_rag import EvidenceAssistant
from evidence_rag.admin_service import ROLE_LEVEL, AdminError, AdminService
from evidence_rag.admin_store import AdminStore

ROOT = Path(__file__).parent
LOCAL_TIMEZONE = ZoneInfo("Asia/Samarkand")
ROLE_LABELS = {
    "superadmin": "Bosh administrator",
    "admin": "Administrator",
    "editor": "Muharrir",
    "viewer": "Kuzatuvchi",
}
STATUS_LABELS = {"success": "Muvaffaqiyatli", "error": "Xato"}
DOCUMENT_STATUS_LABELS = {"indexed": "Indekslangan", "pending": "Indeks kutilmoqda"}
MODE_LABELS = {"offline-retrieval": "Mahalliy qidiruv", "openai": "OpenAI"}
ACTION_LABELS = {
    "create": "Yaratildi",
    "update": "Yangilandi",
    "delete": "O‘chirildi",
    "login": "Tizimga kirdi",
    "logout": "Tizimdan chiqdi",
    "reindex": "Qayta indekslandi",
}
ENTITY_LABELS = {
    "user": "Foydalanuvchi",
    "session": "Sessiya",
    "document": "Hujjat",
    "category": "Kategoriya",
    "feedback": "Feedback",
    "setting": "Sozlama",
    "knowledge_base": "Bilim bazasi",
}


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


def friendly_time(value: str | None) -> str:
    if not value:
        return "—"
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone(LOCAL_TIMEZONE).strftime("%d.%m.%Y %H:%M")


def friendly_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    return f"{size_bytes / 1024:.1f} KB"


def details_text(details: dict) -> str:
    labels = {"role": "Rol", "is_active": "Faol", "filename": "Fayl", "value": "Qiymat"}
    values = []
    for key, value in details.items():
        if key == "role":
            value = ROLE_LABELS.get(str(value), value)
        if isinstance(value, bool):
            value = "Ha" if value else "Yo‘q"
        values.append(f"{labels.get(key, key)}: {value}")
    return "; ".join(values) or "—"


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
        rows = [
            {
                "Savol": item["question"],
                "Javob turi": MODE_LABELS.get(item["mode"], item["mode"] or "—"),
                "Holat": STATUS_LABELS.get(item["status"], item["status"]),
                "Tezlik": f"{item['latency_ms']} ms" if item["latency_ms"] is not None else "—",
                "Vaqt": friendly_time(item["created_at"]),
            }
            for item in data["recent_queries"]
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.info("Hali savollar yozilmagan.")


def documents_page() -> None:
    st.header("Hujjatlar")
    documents = admin.list_documents()
    categories = admin.list_categories()
    if documents:
        rows = [
            {
                "Nomi": item["title"],
                "Fayl": item["filename"],
                "Kategoriya": item["category_name"] or "Kategoriyasiz",
                "Holat": DOCUMENT_STATUS_LABELS.get(item["status"], item["status"]),
                "Hajmi": friendly_size(item["size_bytes"]),
                "Yangilangan": friendly_time(item["updated_at"]),
            }
            for item in documents
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
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
    st.header("Kategoriyalar")
    categories = admin.list_categories()
    if categories:
        rows = [
            {
                "Nomi": item["name"],
                "Tavsif": item["description"] or "—",
                "Hujjatlar soni": item["document_count"],
                "Yangilangan": friendly_time(item["updated_at"]),
            }
            for item in categories
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
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
    st.header("Foydalanuvchilar va rollar")
    users = admin.list_users(st.session_state.user)
    rows = [
        {
            "Ism": item["full_name"],
            "Email": item["email"],
            "Rol": ROLE_LABELS.get(item["role"], item["role"]),
            "Faol": "Ha" if item["is_active"] else "Yo‘q",
            "Oxirgi kirish": friendly_time(item["last_login_at"]),
            "Yaratilgan": friendly_time(item["created_at"]),
        }
        for item in users
    ]
    st.dataframe(rows, width="stretch", hide_index=True)
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
    st.header("Savollar tarixi")
    queries = admin.list_queries(500)
    search = st.text_input("Savol bo‘yicha qidirish").strip().lower()
    status_options = {"Barchasi": None, "Muvaffaqiyatli": "success", "Xato": "error"}
    status_label = st.selectbox("Holat", list(status_options))
    if search:
        queries = [item for item in queries if search in item["question"].lower()]
    if status_options[status_label]:
        queries = [item for item in queries if item["status"] == status_options[status_label]]
    if queries:
        rows = [
            {
                "Vaqt": friendly_time(item["created_at"]),
                "Savol": item["question"],
                "Javob turi": MODE_LABELS.get(item["mode"], item["mode"] or "—"),
                "Holat": STATUS_LABELS.get(item["status"], item["status"]),
                "Tezlik": f"{item['latency_ms']} ms" if item["latency_ms"] is not None else "—",
            }
            for item in queries
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
        selected = st.selectbox(
            "Savol va javobni batafsil ko‘rish",
            queries,
            format_func=lambda item: (
                f"{friendly_time(item['created_at'])} — {item['question'][:90]}"
            ),
        )
        st.markdown("#### Savol")
        st.write(selected["question"])
        st.markdown("#### Javob")
        if selected["answer"]:
            st.write(selected["answer"])
        elif selected["error"]:
            st.error(selected["error"])
        else:
            st.info("Javob mavjud emas.")
        st.markdown("#### Manbalar")
        if selected["citations"]:
            for citation in selected["citations"]:
                st.markdown(f"- {citation}")
        else:
            st.caption("Manba qayd etilmagan.")
    else:
        st.info("Hali query mavjud emas.")


def feedback_page() -> None:
    st.header("Feedback")
    feedback = admin.list_feedback()
    if feedback:
        rows = [
            {
                "Vaqt": friendly_time(item["created_at"]),
                "Baho": "Foydali 👍" if item["rating"] == 1 else "Foydasiz 👎",
                "Savol": item["question"],
                "Izoh": item["comment"] or "—",
            }
            for item in feedback
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
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
    st.header("Sozlamalar")
    labels = {
        "openai_model": ("OpenAI modeli", "Masalan: gpt-5.4-mini"),
        "default_top_k": ("Dalillar soni", "Har bir savol uchun olinadigan manbalar soni"),
        "system_prompt": ("Tizim ko‘rsatmasi", "AI javob berishda bajaradigan asosiy qoida"),
    }
    for setting in admin.get_settings():
        with st.form(f"setting_{setting['key']}"):
            label, help_text = labels.get(setting["key"], (setting["key"], setting["description"]))
            st.subheader(label)
            st.caption(help_text)
            value = st.text_area("Qiymat", value=setting["value"], label_visibility="collapsed")
            if st.form_submit_button("Saqlash", disabled=not role_at_least("admin")):
                try:
                    admin.update_setting(st.session_state.user, setting["key"], value)
                    st.success("Sozlama yangilandi.")
                    st.rerun()
                except AdminError as error:
                    flash_error(error)


def audit_page() -> None:
    st.header("O‘zgarishlar tarixi")
    st.caption("Administratorlar tizimda bajargan muhim amallar")
    logs = admin.audit_logs(500)
    action_values = sorted({item["action"] for item in logs})
    action_options = {
        "Barchasi": None,
        **{ACTION_LABELS.get(item, item): item for item in action_values},
    }
    action_label = st.selectbox("Amal bo‘yicha filter", list(action_options))
    if action_options[action_label]:
        logs = [item for item in logs if item["action"] == action_options[action_label]]
    rows = [
        {
            "Vaqt": friendly_time(item["created_at"]),
            "Kim": item["actor_email"] or "Tizim",
            "Amal": ACTION_LABELS.get(item["action"], item["action"]),
            "Nima o‘zgardi": ENTITY_LABELS.get(item["entity_type"], item["entity_type"]),
            "Tafsilot": details_text(item["details"]),
        }
        for item in logs
    ]
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.info("Tanlangan filter bo‘yicha amallar topilmadi.")


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
    st.caption(f"{user['email']} · {ROLE_LABELS.get(user['role'], user['role'])}")
    pages = ["Dashboard", "Hujjatlar", "Kategoriyalar", "Savollar tarixi", "Feedback", "Sozlamalar"]
    if role_at_least("admin"):
        pages.extend(["Foydalanuvchilar", "O‘zgarishlar tarixi"])
    selected_page = st.radio("Bo‘lim", pages)
    if st.button("Chiqish", use_container_width=True):
        admin.logout(st.session_state.token, user)
        st.session_state.clear()
        st.rerun()

PAGE_HANDLERS = {
    "Dashboard": dashboard_page,
    "Hujjatlar": documents_page,
    "Kategoriyalar": categories_page,
    "Foydalanuvchilar": users_page,
    "Savollar tarixi": history_page,
    "Feedback": feedback_page,
    "Sozlamalar": settings_page,
    "O‘zgarishlar tarixi": audit_page,
}
PAGE_HANDLERS[selected_page]()
