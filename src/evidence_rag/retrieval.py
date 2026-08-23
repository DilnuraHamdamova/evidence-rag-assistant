"""Deterministic TF-IDF retrieval baseline."""

from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .ingest import Chunk


@dataclass(frozen=True)
class SearchResult:
    chunk: Chunk
    score: float


class Retriever:
    def __init__(self, chunks: list[Chunk]):
        if not chunks:
            raise ValueError("Knowledge base has no chunks")
        self.chunks = chunks
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
        self.matrix = self.vectorizer.fit_transform(chunk.text for chunk in chunks)

    def search(self, query: str, top_k: int = 3) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("Question cannot be empty")
        query_vector = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vector, self.matrix)[0]
        indices = scores.argsort()[::-1][: max(1, min(top_k, len(self.chunks)))]
        return [SearchResult(self.chunks[index], float(scores[index])) for index in indices]

