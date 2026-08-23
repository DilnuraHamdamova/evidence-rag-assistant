# Model evaluation

## Release gate

A model may enter production only after the owner records task-specific quality metrics on a protected test set, compares them with the current baseline, and reviews representative failures. The test set must not be used for model selection.

## RAG evaluation

Retrieval is evaluated separately from generation. The minimum retrieval report contains Recall at K and mean reciprocal rank on a versioned question set. Answer review checks factual support, citation correctness, completeness, and refusal when the evidence is absent.

## Regression checks

Every model, prompt, retrieval, or chunking change must rerun the saved evaluation set. A release is blocked when a critical safety case fails or when an agreed primary metric falls below its threshold.

