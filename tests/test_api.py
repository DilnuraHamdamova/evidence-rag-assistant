from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_offline_ask_returns_ranked_citations():
    response = client.post("/ask", json={"question": "How should credentials be handled in an incident?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "offline-retrieval"
    assert payload["citations"][0]["source"] == "incidents.md"

