# GitHub Copilot — Project Context for MisogynAI

This file gives Copilot full context about the MisogynAI project so that suggestions are accurate, consistent, and architecturally aligned from the first line of code.

---

## Project summary

MisogynAI is a containerised Python backend that:
1. Scrapes Bluesky Social (AT Protocol) every 30 minutes for recent posts.
2. Stores raw posts as JSON in MinIO (object store).
3. Embeds posts with a multilingual sentence-transformer and indexes them in ChromaDB.
4. Exposes a Flask REST API that performs RAG (Retrieval-Augmented Generation) to surface misogynistic posts matching a semantic query.
5. Purges posts older than 24 hours from both MinIO and ChromaDB on every scraping cycle.

The long-term goal is to compute a rolling "misogyny index" for the Bluesky network every 30 minutes using a fine-tuned classifier.

---

## Technology stack

| Layer | Choice | Reason |
|---|---|---|
| Scraping scheduler | `APScheduler` (BackgroundScheduler) | Lightweight, runs inside the scraper container, no separate Celery/Redis needed |
| Bluesky API | `atproto` Python SDK | Official AT Protocol client; use `Client` for auth'd requests and `FirehoseSubscribeReposClient` for the firehose |
| Object store | `MinIO` (`minio` Python SDK) | Persistent raw post storage; one bucket per day or a single `posts` bucket |
| Vector store | `ChromaDB` (HTTP client mode) | Simple deployment, runs as its own container, integrates well with sentence-transformers |
| Embedding model | `paraphrase-multilingual-mpnet-base-v2` (sentence-transformers) | Multilingual (ES + EN), good semantic quality, CPU-friendly |
| LLM | `llama.cpp` (llama-server) via OpenAI-compatible API | Local inference, no external API keys, GGUF quantised models |
| API framework | `Flask` | Required by the assignment; keep it thin — business logic lives in ingestion/ and retrieval/ modules |
| Containerisation | `Docker` + `docker-compose` | All five services orchestrated in one file |

---

## Service names (Docker Compose internal DNS)

Always use these hostnames when one service calls another:

| Service | Internal hostname | Port |
|---|---|---|
| Scraper | `scraper` | — |
| Flask API | `flask_app` | 5000 |
| LLM (llama.cpp) | `llm` | 8080 |
| MinIO | `minio` | 9000 |
| ChromaDB | `chromadb` | 8000 |

Environment variables are injected by docker-compose; never hardcode hostnames or credentials.

---

## Environment variables

The following env vars are always available inside containers. Define them in `.env` and reference in `docker-compose.yml`:

```
BLUESKY_HANDLE=yourhandle.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

MINIO_URL=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=posts

CHROMADB_HOST=chromadb
CHROMADB_PORT=8000
CHROMA_COLLECTION=bluesky_posts

LLM_URL=http://llm:8080

SCRAPE_INTERVAL_MINUTES=30
POST_TTL_HOURS=24

EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2
```

---

## Data model — Bluesky post (the canonical dict throughout the codebase)

```python
{
    "uri": str,           # AT URI, used as MinIO object key and ChromaDB document ID
    "cid": str,
    "author_did": str,
    "author_handle": str,
    "text": str,          # full post text
    "created_at": str,    # ISO 8601, from Bluesky
    "scraped_at": str,    # ISO 8601, set by scraper
    "scraped_at_ts": float,  # Unix timestamp, used for TTL filtering in ChromaDB metadata
    "images": [           # may be empty list
        {"alt": str, "thumb_url": str}
    ],
    "langs": list[str],
    "labels": list[str],  # Bluesky content labels
    "like_count": int,
    "repost_count": int,
}
```

---

## Embedding strategy

Build the embedding string like this before calling `encoder.encode()`:

```python
def build_embedding_text(post: dict) -> str:
    parts = [post["text"]]
    for img in post.get("images", []):
        if img.get("alt"):
            parts.append(f"[IMAGE] {img['alt']}")
    return " ".join(parts)
```

This makes the embedding multimodal-lite: it includes image alt-text alongside post text, without needing a full vision model. Full CLIP image embeddings are a future extension.

---

## ChromaDB schema

Collection name: `bluesky_posts`

Each document stored in ChromaDB:

```python
collection.add(
    ids=[post["uri"]],                    # AT URI as unique ID
    documents=[embedding_text],           # text used for embedding
    embeddings=[embedding_vector],        # precomputed float list
    metadatas=[{
        "uri": post["uri"],
        "author_handle": post["author_handle"],
        "text": post["text"],
        "created_at": post["created_at"],
        "scraped_at": post["scraped_at"],
        "scraped_at_ts": post["scraped_at_ts"],  # CRITICAL for TTL
        "langs": ",".join(post.get("langs", [])),
        "like_count": post.get("like_count", 0),
    }]
)
```

---

## TTL purge logic

On every scrape cycle, after ingesting new posts, run the purge:

```python
import time

def purge_old_posts(collection, minio_client, bucket, ttl_hours=24):
    cutoff_ts = time.time() - (ttl_hours * 3600)
    # ChromaDB: query all, filter by scraped_at_ts < cutoff
    # Then delete from ChromaDB by ID and from MinIO by object key (= URI)
```

ChromaDB supports metadata filtering with `where={"scraped_at_ts": {"$lt": cutoff_ts}}`.

---

## Scraper design notes

- Use `atproto` SDK's `Client` with app password authentication.
- Primary source: `app.bsky.feed.searchPosts(q=query, limit=100)` — search for terms associated with misogyny (see keyword list below).
- Secondary source (optional): subscribe to the AT Protocol firehose and filter locally.
- Rate limits: Bluesky public API allows ~3000 req/5min. Respect this; add `time.sleep()` between paginated calls.
- Store one JSON file per post in MinIO: object key = `{uri_safe(post.uri)}.json`.

### Seed query keywords for scraping

The scraper should search for a curated list of terms known to appear in misogynistic content. Store this list in `scraper/keywords.py` so it can be extended without changing logic:

```python
MISOGYNY_SEED_QUERIES = [
    "feminazi",
    "mujeres no saben",
    "las mujeres son",
    "women belong",
    "make me a sandwich",
    # ... extend as needed
]
```

Rotate through queries across scraping cycles to stay within rate limits.

---

## Flask API — endpoint specifications

### `POST /query`
- Body: `{"question": str, "top_k": int (default 5)}`
- Retrieves top_k posts from ChromaDB matching the question.
- Assembles a RAG prompt and calls the LLM.
- Returns:
```json
{
  "question": "...",
  "answer": "...",
  "sources": [
    {
      "uri": "at://...",
      "author_handle": "user.bsky.social",
      "text": "post text",
      "score": 0.87,
      "created_at": "2026-03-16T10:00:00Z"
    }
  ]
}
```

### `GET /stats`
- Returns misogyny-related stats for the current window:
```json
{
  "total_posts_indexed": 1243,
  "window_hours": 24,
  "last_scrape": "2026-03-16T10:30:00Z",
  "top_authors": [...],
  "langs_breakdown": {"es": 430, "en": 812}
}
```

### `GET /health`
- Pings MinIO, ChromaDB, and LLM service.
- Returns 200 only if all three are reachable.

---

## LLM prompt template for RAG

```python
SYSTEM_PROMPT = (
    "You are an assistant helping researchers analyse misogynistic content on social media. "
    "You are given a set of real posts retrieved from Bluesky. "
    "Answer the researcher's question based solely on the provided posts. "
    "Do not add information not present in the posts. "
    "If no post is clearly relevant, say so explicitly. "
    "Cite posts by their index [1], [2], etc."
)
```

---

## Module responsibilities

| File | Responsibility |
|---|---|
| `scraper/bluesky_client.py` | Wraps `atproto` SDK; exposes `search_posts(query, limit)` and `get_recent_posts(limit)` |
| `scraper/scraper.py` | APScheduler loop; calls bluesky_client, stores to MinIO, triggers ingestion |
| `flask_app/ingestion/minio_client.py` | Upload, download, list, delete objects in MinIO |
| `flask_app/ingestion/embedder.py` | Loads sentence-transformer, builds embedding text, returns vectors |
| `flask_app/ingestion/ttl.py` | Purge function: ChromaDB + MinIO cleanup for expired posts |
| `flask_app/retrieval/retriever.py` | ChromaDB query wrapper; returns list of post dicts with scores |
| `flask_app/pipeline/rag.py` | Assembles prompt from retrieved posts, calls LLM, returns answer + sources |
| `flask_app/app.py` | Flask routes only; delegate all logic to above modules |

---

## Code style and conventions

- Python 3.11+.
- Type hints on all function signatures.
- Each module has a `__main__` block for standalone testing.
- Use `structlog` or plain `logging` (not `print`) for all output.
- Configuration is read exclusively from environment variables via `os.getenv()`.
- No hardcoded credentials, paths, or model names anywhere except `.env.example`.
- All Docker images pin a specific tag (no `:latest` in production builds, except MinIO and ChromaDB which are controlled externally).

---

## What NOT to do (common mistakes)

- Do NOT use any external LLM API (OpenAI, Anthropic, Groq). The LLM must run locally via llama.cpp.
- Do NOT commit model `.gguf` weight files to the repository.
- Do NOT hardcode `localhost` — always use Docker service names.
- Do NOT return empty results silently — raise a clear error if ChromaDB collection is empty.
- Do NOT scrape without respecting Bluesky rate limits.
- Do NOT store user credentials in source code — only in `.env` (git-ignored).

---

## Future extensions (do not implement yet, but keep in mind for clean interfaces)

1. **Misogyny classifier**: a fine-tuned `bert-base-multilingual-cased` model loaded alongside the embedder. Each post gets a `misogyny_score: float` stored in ChromaDB metadata.
2. **Rolling index endpoint**: `GET /index/timeseries` returns average misogyny score per 30-min window over the last 24 hours.
3. **CLIP image embeddings**: fuse CLIP image vectors with text vectors for posts that contain images.
4. **Alerting**: webhook or email when the rolling index exceeds a configurable threshold.
