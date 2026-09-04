from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_offline_ask_returns_ranked_citations():
    response = client.post(
        "/ask", json={"question": "How should credentials be handled in an incident?"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "offline-retrieval"
    assert payload["citations"][0]["source"] == "incidents.md"


def test_prometheus_metrics_are_exposed():
    client.post("/ask", json={"question": "How should incidents be contained?"})
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "hujjat_rag_queries_total" in response.text
    assert "hujjat_http_request_duration_seconds" in response.text
    assert "hujjat_documents" in response.text
