"""Load and chunk local Markdown or text documents."""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    source: str
    section: str
    text: str

    @property
    def citation(self) -> str:
        return f"{self.source} — {self.section}"


def _paragraphs(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", item).strip() for item in re.split(r"\n\s*\n", text) if item.strip()]


def chunk_document(path: Path, max_words: int = 140) -> list[Chunk]:
    text = path.read_text(encoding="utf-8")
    section = "Overview"
    chunks: list[Chunk] = []
    buffer: list[str] = []
    word_count = 0

    def flush() -> None:
        nonlocal buffer, word_count
        if buffer:
            chunks.append(Chunk(path.name, section, " ".join(buffer)))
            buffer = []
            word_count = 0

    for paragraph in _paragraphs(text):
        if paragraph.startswith("#"):
            flush()
            section = paragraph.lstrip("# ").strip()
            continue
        words = paragraph.split()
        if buffer and word_count + len(words) > max_words:
            flush()
        buffer.append(paragraph)
        word_count += len(words)
    flush()
    return chunks


def load_knowledge(directory: Path) -> list[Chunk]:
    paths = sorted([*directory.glob("*.md"), *directory.glob("*.txt")])
    return [chunk for path in paths for chunk in chunk_document(path)]

