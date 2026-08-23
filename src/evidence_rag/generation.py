"""Optional grounded generation through the OpenAI Responses API."""

import os
from collections.abc import Callable

from openai import OpenAI

from .retrieval import SearchResult

Generator = Callable[[str, list[SearchResult]], str]


def openai_generator(question: str, results: list[SearchResult]) -> str:
    context = "\n\n".join(
        f"SOURCE [{item.chunk.citation}]\n{item.chunk.text}" for item in results
    )
    prompt = f"""Answer the question using only the supplied sources.
If the answer is absent, say that the knowledge base does not contain it.
Keep the answer concise and cite every factual claim as [filename — section].

QUESTION:
{question}

SOURCES:
{context}
"""
    client = OpenAI()
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        input=prompt,
        max_output_tokens=350,
    )
    return response.output_text.strip()

