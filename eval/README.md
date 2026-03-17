# Evaluation dataset — instructions and schema

This directory contains the hand-annotated dataset used to measure retrieval quality.

---

## File: `eval_dataset.json`

Each entry represents a query that has a known relevant post in the Bluesky corpus.

```json
[
  {
    "id": "eval_001",
    "question": "posts that tell women they don't belong in tech",
    "relevant_uri": "at://did:plc:example/app.bsky.feed.post/abc123",
    "relevant_text": "Women are too emotional to be good engineers. Stick to HR.",
    "expected_theme": "women in STEM exclusion",
    "language": "en",
    "annotator_notes": "Clear gender-based exclusion from profession"
  }
]
```

### Fields

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique identifier for this eval example |
| `question` | string | The natural language query used for retrieval |
| `relevant_uri` | string | AT URI of the ground-truth relevant post |
| `relevant_text` | string | The text of that post (first 150 chars sufficient for matching) |
| `expected_theme` | string | Short label for the type of misogyny (see taxonomy below) |
| `language` | string | `"es"`, `"en"`, or `"es+en"` |
| `annotator_notes` | string | Optional: why this was annotated as relevant |

---

## Annotation taxonomy (expected_theme values)

Use these consistent labels when annotating:

- `professional_exclusion` — women told they don't belong in certain jobs/fields
- `appearance_shaming` — attacks based on physical appearance
- `domestic_role_enforcement` — women told their place is in the home
- `intellectual_inferiority` — claims women are less intelligent/rational
- `sexual_objectification` — reducing women to sexual objects
- `victim_blaming` — blaming women for violence or harassment they experienced
- `general_hostility` — hate speech not fitting above categories

---

## Dataset construction guidelines

1. Scrape Bluesky for a few cycles and collect real posts.
2. Manually review and identify 10–20 posts that are clearly misogynistic.
3. For each post, write a natural language question that should retrieve it.
4. Record the post's AT URI and the first ~150 characters of its text.
5. Save as `eval_dataset.json` following the schema above.

**Minimum dataset size:** 10 entries across at least 3 different themes.

**Language balance:** aim for at least 30% Spanish-language examples given the multilingual scope.

---

## Metrics computed by `evaluate.py`

Run against your live ChromaDB index:

```bash
python eval/evaluate.py --k 1 3 5
```

Outputs:
- Hit Rate @ 1, 3, 5
- MRR
- Precision @ 1, 3, 5
- Per-theme breakdown (optional)

Results are saved to `results/retrieval_metrics.json`.
