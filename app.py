"""Streamlit interface for the Evidence RAG Assistant."""

from pathlib import Path

import streamlit as st

from evidence_rag import EvidenceAssistant

ROOT = Path(__file__).parent


@st.cache_resource
def assistant() -> EvidenceAssistant:
    return EvidenceAssistant(ROOT / "knowledge")


st.set_page_config(page_title="Evidence RAG Assistant", page_icon="🔎", layout="wide")
st.title("🔎 Evidence RAG Assistant")
st.caption("Citation-first answers from a local AI operations handbook")

with st.sidebar:
    use_openai = st.toggle("Generate with OpenAI", value=False)
    top_k = st.slider("Evidence chunks", 1, 5, 3)
    st.info("Offline mode needs no API key. OpenAI mode reads OPENAI_API_KEY from the environment.")

question = st.text_input(
    "Ask a question",
    value="What must happen before a model is deployed?",
)
if st.button("Find evidence", type="primary"):
    try:
        answer = assistant().ask(question, top_k=top_k, use_openai=use_openai)
        st.subheader("Answer")
        st.write(answer.text)
        st.caption(f"Mode: {answer.mode}")
        st.subheader("Retrieved evidence")
        for rank, item in enumerate(answer.results, 1):
            with st.expander(f"{rank}. {item.chunk.citation} · score {item.score:.3f}"):
                st.write(item.chunk.text)
    except ValueError as error:
        st.error(str(error))

