"""Public Streamlit interface for Hujjat AI."""

from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter

import streamlit as st

from evidence_rag import EvidenceAssistant
from evidence_rag.admin_service import AdminService
from evidence_rag.admin_store import AdminStore
from evidence_rag.generation import generate_with_openai

ROOT = Path(__file__).parent


@st.cache_resource
def runtime() -> tuple[EvidenceAssistant, AdminService]:
    knowledge_dir = ROOT / "knowledge"
    database_path = Path(os.getenv("HUJJAT_DATABASE_PATH", ROOT / "data" / "admin.db"))
    admin = AdminService(AdminStore(database_path), knowledge_dir)

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

    return EvidenceAssistant(knowledge_dir, configured_generator), admin


assistant, admin = runtime()
settings = {item["key"]: item["value"] for item in admin.get_settings()}

st.set_page_config(page_title="Hujjat AI", page_icon="🔎", layout="wide")
st.title("🔎 Hujjat AI")
st.caption("Mahalliy hujjatlardan citation bilan asoslangan javoblar")

with st.sidebar:
    use_openai = st.toggle("OpenAI bilan javob yaratish", value=False)
    configured_top_k = max(1, min(int(settings["default_top_k"]), 10))
    top_k = st.slider("Dalillar soni", 1, 10, configured_top_k)
    st.info("Offline rejim API key talab qilmaydi. OpenAI rejimi OPENAI_API_KEY’dan foydalanadi.")

question = st.text_input(
    "Savolingizni kiriting",
    value="What must happen before a model is deployed?",
)
if st.button("Dalil topish", type="primary"):
    started = perf_counter()
    try:
        answer = assistant.ask(question, top_k=top_k, use_openai=use_openai)
        query_id = admin.record_query(
            question,
            answer.text,
            answer.mode,
            answer.citations,
            round((perf_counter() - started) * 1000),
        )
        st.session_state.last_query_id = query_id
        st.subheader("Javob")
        st.write(answer.text)
        st.caption(f"Rejim: {answer.mode} · Query #{query_id}")
        st.subheader("Topilgan dalillar")
        for rank, item in enumerate(answer.results, 1):
            with st.expander(f"{rank}. {item.chunk.citation} · score {item.score:.3f}"):
                st.write(item.chunk.text)
    except ValueError as error:
        admin.record_query(
            question,
            None,
            None,
            [],
            round((perf_counter() - started) * 1000),
            error=str(error),
        )
        st.error(str(error))

if "last_query_id" in st.session_state:
    st.caption("Javob foydali bo‘ldimi?")
    positive, negative, _ = st.columns([1, 1, 8])
    if positive.button("👍 Ha"):
        admin.add_feedback(None, st.session_state.last_query_id, 1)
        del st.session_state.last_query_id
        st.success("Rahmat!")
    if negative.button("👎 Yo‘q"):
        admin.add_feedback(None, st.session_state.last_query_id, -1)
        del st.session_state.last_query_id
        st.success("Rahmat, feedback saqlandi.")
