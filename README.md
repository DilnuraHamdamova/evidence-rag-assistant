# Evidence RAG Assistant

[![CI](https://github.com/DilnuraHamdamova/evidence-rag-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/DilnuraHamdamova/evidence-rag-assistant/actions/workflows/ci.yml)

A citation-first retrieval-augmented generation project for an AI operations handbook. It demonstrates document ingestion, chunking, TF-IDF retrieval, versioned evaluation, grounded LLM generation, a Streamlit interface, a FastAPI service, tests, CI, and Docker delivery.

The application works without a paid API in **offline retrieval mode**. If `OPENAI_API_KEY` is present, it can generate a concise grounded answer with the OpenAI Responses API. Retrieved source passages remain visible in both modes.

## Architecture

```text
Markdown knowledge base
        ↓
paragraph/section chunking
        ↓
TF-IDF index + cosine retrieval
        ↓
top-k evidence ──→ offline evidence answer
        └────────→ optional OpenAI grounded answer
                         ↓
                Streamlit UI / FastAPI
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
streamlit run app.py
```

OpenAI mode is optional:

```bash
export OPENAI_API_KEY="your-key"
export OPENAI_MODEL="gpt-5.4-mini"
streamlit run app.py
```

Never commit `.env` or an API key. API usage may incur charges from the provider.

## API and Docker

```bash
uvicorn api:app --reload
curl -X POST http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What must happen before deployment?","top_k":3}'
```

```bash
docker build -t evidence-rag-assistant .
docker run --rm -p 8000:8000 evidence-rag-assistant
```

## Evaluation

`evals/questions.json` is a versioned six-question retrieval set. Run:

```bash
python evaluate.py
pytest -q
ruff check .
```

The evaluation reports Recall@3 and mean reciprocal rank. These metrics test retrieval only; they are not presented as proof that every generated answer is correct. The small original handbook is a demonstration corpus, so results should not be generalized to a large production knowledge base.

Current checked result on the six-question set: **Recall@3 1.000** and **MRR 0.806**.

## Responsible-use boundaries

- Answers are grounded only in the supplied local documents.
- The interface exposes retrieved passages and citations for verification.
- OpenAI generation is opt-in and requires a separately managed API key.
- Do not ingest confidential or regulated data without an approved architecture.
- This demo is not a substitute for security, legal, medical, or policy review.

## Project structure

```text
src/evidence_rag/   ingestion, retrieval, generation, orchestration
knowledge/          original sample AI operations handbook
evals/              versioned retrieval questions
tests/              unit and API tests without real external calls
app.py              Streamlit interface
api.py              FastAPI service
Dockerfile          production-style API container
```

## Technical choice

TF-IDF is intentionally used as a transparent retrieval baseline. A production extension would compare it with multilingual embedding retrieval on a larger labeled evaluation set before changing the default.
