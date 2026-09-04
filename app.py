"""Public Streamlit interface for Hujjat AI."""

from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter

import streamlit as st
import streamlit.components.v1 as components

from evidence_rag import EvidenceAssistant
from evidence_rag.admin_service import AdminService
from evidence_rag.admin_store import AdminStore
from evidence_rag.generation import generate_with_openai
from evidence_rag.portfolio import (
    DeploymentError,
    Portfolio,
    PortfolioError,
    deploy_to_netlify,
    deploy_to_vercel,
    parse_projects,
    portfolio_zip,
    render_portfolio,
)

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
with st.sidebar:
    page = st.radio("Bo‘lim", ["🔎 Hujjat qidirish", "✨ Portfolio yaratish"])

if page == "🔎 Hujjat qidirish":
    st.title("🔎 Hujjat AI")
    st.caption("Mahalliy hujjatlardan citation bilan asoslangan javoblar")
    with st.sidebar:
        use_openai = st.toggle("OpenAI bilan javob yaratish", value=False)
        configured_top_k = max(1, min(int(settings["default_top_k"]), 10))
        top_k = st.slider("Dalillar soni", 1, 10, configured_top_k)
        st.info("Offline rejim API key talab qilmaydi. OpenAI rejimi OPENAI_API_KEY’dan foydalanadi.")
    question = st.text_input("Savolingizni kiriting", value="What must happen before a model is deployed?")
    if st.button("Dalil topish", type="primary"):
        started = perf_counter()
        try:
            answer = assistant.ask(question, top_k=top_k, use_openai=use_openai)
            query_id = admin.record_query(question, answer.text, answer.mode, answer.citations,
                                          round((perf_counter() - started) * 1000))
            st.session_state.last_query_id = query_id
            st.subheader("Javob")
            st.write(answer.text)
            st.caption(f"Rejim: {answer.mode} · Query #{query_id}")
            st.subheader("Topilgan dalillar")
            for rank, item in enumerate(answer.results, 1):
                with st.expander(f"{rank}. {item.chunk.citation} · score {item.score:.3f}"):
                    st.write(item.chunk.text)
        except ValueError as error:
            admin.record_query(question, None, None, [], round((perf_counter() - started) * 1000), error=str(error))
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
else:
    st.title("✨ Portfolio yaratish")
    st.caption("Ma’lumotlaringizdan tayyor sayt yarating va Vercel yoki Netlify’da chop eting.")
    left, right = st.columns(2)
    with left:
        name = st.text_input("Ism va familiya *")
        headline = st.text_input("Kasbiy sarlavha *")
        bio = st.text_area("O‘zingiz haqingizda *", height=130)
        location = st.text_input("Joylashuv")
        email = st.text_input("Email")
        skills_text = st.text_input("Ko‘nikmalar", placeholder="Python, FastAPI, RAG")
    with right:
        avatar_url = st.text_input("Rasm URL")
        github_url = st.text_input("GitHub URL")
        linkedin_url = st.text_input("LinkedIn URL")
        accent_color = st.color_picker("Asosiy rang", "#6d5dfc")
        projects_text = st.text_area("Loyihalar", help="Nomi | Tavsifi | URL (har biri yangi qatorda)", height=150)
    if st.button("Portfolio yaratish", type="primary", use_container_width=True):
        try:
            portfolio = Portfolio(name=name, headline=headline, bio=bio, email=email, location=location,
                                  avatar_url=avatar_url, github_url=github_url, linkedin_url=linkedin_url,
                                  skills=[x.strip() for x in skills_text.split(",") if x.strip()],
                                  projects=parse_projects(projects_text), accent_color=accent_color)
            st.session_state.portfolio_document = render_portfolio(portfolio)
            st.success("Portfolio tayyor!")
        except PortfolioError as error:
            st.error(str(error))
    if document := st.session_state.get("portfolio_document"):
        st.subheader("Ko‘rinishi")
        components.html(document, height=700, scrolling=True)
        st.download_button("⬇️ ZIP yuklab olish", portfolio_zip(document), "portfolio.zip", "application/zip", use_container_width=True)
        st.divider()
        st.subheader("Internetga joylash")
        provider = st.radio("Platforma", ["Vercel", "Netlify"], horizontal=True)
        site_name = st.text_input("Sayt nomi", placeholder="dilnura-portfolio")
        token = st.text_input(f"{provider} access token", type="password",
                             help="Token saqlanmaydi va faqat shu deploy so‘rovida ishlatiladi.")
        team_id = st.text_input("Vercel Team ID (ixtiyoriy)") if provider == "Vercel" else ""
        if st.button(f"🚀 {provider}’ga deploy qilish", use_container_width=True):
            try:
                with st.spinner("Sayt joylanmoqda..."):
                    result = (deploy_to_vercel(document, token, site_name, team_id=team_id)
                              if provider == "Vercel" else deploy_to_netlify(document, token, site_name))
                st.success(f"Portfolio {result.provider}’ga muvaffaqiyatli joylandi!")
                st.link_button("Saytni ochish ↗", result.url, use_container_width=True)
            except (PortfolioError, DeploymentError) as error:
                st.error(str(error))
