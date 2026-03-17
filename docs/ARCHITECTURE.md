# MisogynAI — Architecture Document

## Overview

MisogynAI is a five-container system that monitors Bluesky Social for misogynistic content using a Retrieval-Augmented Generation (RAG) pipeline. The system operates on a 30-minute scraping cycle, maintains a 24-hour rolling window of indexed posts, and exposes a REST API for semantic retrieval and grounded answer generation.

---

## Container map

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker network                           │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │   scraper    │    │  flask_app   │    │       llm        │  │
│  │              │    │              │    │  llama.cpp       │  │
│  │ APScheduler  │    │  Flask 5000  │    │  :8080           │  │
│  │ atproto SDK  │    │  RAG API     │    │  GGUF model      │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────────────┘  │
│         │                  │  ▲                                 │
│         │ store/ingest      │  │ LLM call                       │
│         ▼                  ▼  │                                 │
│  ┌──────────────┐    ┌──────────────┐                           │
│  │    minio     │    │   chromadb   │                           │
│  │  :9000/9001  │    │   :8000      │                           │
│  │  raw posts   │    │  embeddings  │                           │
│  │  (JSON)      │    │  + metadata  │                           │
│  └──────────────┘    └──────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data flows

### Flow 1 — Scraping cycle (every 30 minutes)

```
APScheduler trigger
      │
      ▼
bluesky_client.search_posts(keyword)   ← Bluesky AT Protocol API
      │
      ▼
for each post:
  1. minio_client.put_object(post_json)      → MinIO bucket "posts"
  2. embedder.build_embedding_text(post)
  3. encoder.encode(embedding_text)
  4. chromadb.collection.add(id, doc, emb, metadata)
      │
      ▼
ttl.purge_old_posts(cutoff = now - 24h)
  - chromadb: delete where scraped_at_ts < cutoff
  - minio: delete corresponding JSON objects
```

### Flow 2 — RAG query

```
POST /query  {"question": "...", "top_k": 5}
      │
      ▼
retriever.retrieve(question, top_k)
  └─ encoder.encode(question)
  └─ chromadb.collection.query(query_embeddings, n_results=top_k)
  └─ returns list of {text, metadata, score}
      │
      ▼
rag.build_prompt(question, retrieved_posts)
  └─ system prompt + post context blocks + user question
      │
      ▼
LLM call → http://llm:8080/v1/chat/completions
      │
      ▼
Response: {question, answer, sources[]}
```

---

## Bluesky data acquisition strategy

### Option A — Search API (primary, simpler)

`app.bsky.feed.searchPosts` accepts a query string and returns matching posts. The scraper rotates through a list of seed keywords associated with misogynistic language. This gives targeted recall but misses content that doesn't match exact keywords.

Pagination via `cursor` parameter allows fetching up to the API's rate limit per cycle.

### Option B — Firehose (advanced, higher volume)

The AT Protocol firehose (`com.atproto.sync.subscribeRepos`) streams all new posts in real time. The scraper subscribes and filters locally for language and keyword matches. This captures far more content but requires careful buffer management and rate-of-write control into ChromaDB.

**Recommended starting point:** Option A (search API) to validate the pipeline, then extend to firehose.

---

## Embedding model choice

**Model:** `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`

Rationale:
- Supports 50+ languages including Spanish and English, which are the dominant languages on Bluesky for this use case.
- 768-dimensional embeddings — good quality/cost trade-off.
- Runs on CPU without performance issues for this volume.
- Well-tested with ChromaDB.

**Embedding text construction:**
Post text is combined with image alt-texts into a single string before encoding. This provides a lightweight multimodal signal without requiring a vision model.

---

## TTL and data lifecycle

The 24-hour window is enforced at two layers:

| Layer | Mechanism |
|---|---|
| ChromaDB | `collection.delete(where={"scraped_at_ts": {"$lt": cutoff_ts}})` |
| MinIO | List objects, parse `scraped_at` from stored JSON metadata, delete expired keys |

The TTL purge runs at the end of every scraping cycle, after new posts are ingested.

This design means the vector index always reflects the last 24 hours of scraped content, regardless of when the system started.

---

## LLM service

**Default:** `llama.cpp` (llama-server) with a GGUF quantised model.

Recommended models (in order of preference by hardware):
- `Mistral-7B-Instruct-v0.2.Q4_K_M.gguf` — best instruction following, runs on 8 GB RAM
- `Llama-3.1-8B-Instruct.Q4_K_M.gguf` — strong multilingual
- `Qwen2.5-3B-Instruct.Q5_K_M.gguf` — for machines with ≤ 6 GB RAM

The Flask app calls the LLM via the OpenAI-compatible `/v1/chat/completions` endpoint. No external API keys are used.

---

## Security considerations (for future hardening)

- Bluesky app password (not account password) stored only in `.env`, never in source.
- MinIO credentials are local-only defaults; replace in production.
- Flask API has no authentication in this version; add API key middleware before exposing externally.
- No user data is persisted beyond 24 hours by design (GDPR-friendly).

---

## Evaluation approach

Retrieval quality is measured on a hand-annotated dataset of misogynistic Bluesky posts.

Metrics computed at k ∈ {1, 3, 5}:
- **Hit Rate @ k** — fraction of queries where at least one relevant post appears in top k
- **MRR** — mean reciprocal rank of the first relevant result
- **Precision @ k** — fraction of top-k results that are relevant

The evaluation script lives in `eval/evaluate.py` and reads `eval/eval_dataset.json`.

---

## Future architecture extensions

### Misogyny classifier integration

A fine-tuned binary classifier (e.g., `bert-base-multilingual-cased` fine-tuned on a misogyny dataset) would run as part of the ingestion pipeline. Each post receives a `misogyny_score` field stored in ChromaDB metadata. This enables:

- Filtering retrieval to only return posts above a score threshold.
- Computing a rolling average `misogyny_index` per 30-minute window.
- Exposing `GET /index/timeseries` for visualisation.

### CLIP image embeddings

For posts with images, CLIP embeddings of the thumbnail could be fused with the text embedding (concatenation or weighted average) before storing in ChromaDB. This would improve retrieval for memes and image-based misogyny that contains little text.
