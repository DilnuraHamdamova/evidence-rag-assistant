"""RAG orchestration with transparent offline fallback."""

import os
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from .generation import Generator, openai_generator
from .ingest import load_knowledge
from .retrieval import Retriever, SearchResult


@dataclass(frozen=True)
class Answer:
    text: str
    citations: list[str]
    mode: str
    results: list[SearchResult]


class EvidenceAssistant:
    def __init__(self, knowledge_dir: Path, generator: Generator | None = None):
        self.knowledge_dir = knowledge_dir
        self._lock = RLock()
        self.retriever = Retriever(load_knowledge(knowledge_dir))
        self.generator = generator

    def reindex(self) -> int:
        """Atomically rebuild the in-memory retrieval index from disk."""
        retriever = Retriever(load_knowledge(self.knowledge_dir))
        with self._lock:
            self.retriever = retriever
        return len(retriever.chunks)

    def ask(self, question: str, top_k: int = 3, use_openai: bool = False) -> Answer:
        with self._lock:
            retriever = self.retriever
        results = retriever.search(question, top_k)
        citations = list(dict.fromkeys(item.chunk.citation for item in results))
        generator = self.generator
        if use_openai and generator is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API_KEY is required for generated answers")
            generator = openai_generator
        if use_openai and generator:
            return Answer(generator(question, results), citations, "openai", results)

        best = results[0]
        text = f"Most relevant evidence: {best.chunk.text}\n\nSource: [{best.chunk.citation}]"
        return Answer(text, citations, "offline-retrieval", results)
