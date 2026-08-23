"""Run the versioned retrieval evaluation set."""

import json
from pathlib import Path

from evidence_rag import EvidenceAssistant

ROOT = Path(__file__).parent
assistant = EvidenceAssistant(ROOT / "knowledge")
questions = json.loads((ROOT / "evals/questions.json").read_text(encoding="utf-8"))

ranks: list[int | None] = []
for item in questions:
    results = assistant.retriever.search(item["question"], top_k=3)
    rank = next(
        (index for index, result in enumerate(results, 1) if result.chunk.source == item["expected_source"]),
        None,
    )
    ranks.append(rank)
    print(f"{'PASS' if rank else 'FAIL'} rank={rank} question={item['question']}")

recall_at_3 = sum(rank is not None for rank in ranks) / len(ranks)
mrr = sum(1 / rank for rank in ranks if rank is not None) / len(ranks)
print(f"Recall@3: {recall_at_3:.3f}")
print(f"MRR: {mrr:.3f}")

