from pathlib import Path

import pytest

from evidence_rag import EvidenceAssistant
from evidence_rag.ingest import load_knowledge

ROOT = Path(__file__).parents[1]


def test_knowledge_is_chunked_with_sources():
    chunks = load_knowledge(ROOT / "knowledge")
    assert len(chunks) >= 10
    assert all(chunk.source.endswith(".md") for chunk in chunks)


def test_retrieval_finds_deployment_source():
    assistant = EvidenceAssistant(ROOT / "knowledge")
    results = assistant.retriever.search("What must happen before deployment?", top_k=3)
    assert results[0].chunk.source == "deployment.md"


def test_offline_answer_contains_citation():
    assistant = EvidenceAssistant(ROOT / "knowledge")
    answer = assistant.ask("How should a severe incident be contained?")
    assert answer.mode == "offline-retrieval"
    assert "[incidents.md — Containment]" in answer.text


def test_injected_generator_is_used_without_real_api_call():
    def fake_generator(question, results):
        return f"Grounded answer [{results[0].chunk.citation}]"

    assistant = EvidenceAssistant(ROOT / "knowledge", generator=fake_generator)
    answer = assistant.ask("How is retrieval evaluated?", use_openai=True)
    assert answer.mode == "openai"
    assert "evaluation.md" in answer.text


def test_empty_question_is_rejected():
    assistant = EvidenceAssistant(ROOT / "knowledge")
    with pytest.raises(ValueError, match="cannot be empty"):
        assistant.ask(" ")

