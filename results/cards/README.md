# Result Cards

This directory stores lightweight result cards for future EmotionVector experiments.

Rules:

- Track compact JSON or Markdown summaries only.
- Do not store model weights, hidden states, vector tensors, large generation logs, database dumps, or local cache files here.
- Large artifacts must be referenced by local-only pointers in the result card.
- Sampled failure cases should be preserved when they are small enough to review.

Every future experiment should produce a result card compatible with `result_card.schema.json`.
