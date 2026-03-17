# MisogynAI — Bluesky Misogyny RAG Monitor

> Real-time retrieval-augmented system for detecting and analysing misogynistic content on Bluesky Social.

---

## What this project does

This system continuously scrapes the Bluesky Social network via its public AT Protocol API every 30 minutes, stores raw posts in MinIO, indexes them in ChromaDB using multimodal embeddings, and exposes a RAG-powered REST API that lets you retrieve misogynistic posts by semantic query.

Posts older than 24 hours are automatically purged from both the vector store and the object store, keeping the index focused on the current state of the network.

The long-term goal is to attach a fine-tuned misogyny classifier and produce a rolling "misogyny index" for Bluesky, updated every 30 minutes.

---

## High-level architecture

```
Bluesky AT Protocol API
        |
        | (every 30 min, via APScheduler)
        v
  [ Scraper Service ]  ──►  MinIO (raw posts as JSON)
        |
        v
  [ Ingestion Pipeline ]
    - Multimodal embedding (text + image alt-text)
    - ChromaDB indexing
    - TTL enforcement (delete posts > 24h)
        |
        v
  [ Flask RAG API ]
    POST /query       ← semantic search for misogynistic posts
    GET  /stats       ← misogyny index over time
    GET  /health
        |
        v
  [ LLM Service ]  (llama.cpp or vLLM, local, no external API)
    - Grounded answer generation
    - Optional: misogyny scoring per retrieved chunk
        |
        v
  [ Frontend ]  (optional, Streamlit or static HTML)
```

---

## Repository structure (target)

```
misogynai/
├── docker-compose.yml
├── .env.example
├── README.md
│
├── scraper/
│   ├── Dockerfile
│   ├── scraper.py          # APScheduler + Bluesky AT Proto client
│   ├── bluesky_client.py   # AT Protocol wrapper (firehose + search)
│   └── requirements.txt
│
├── flask_app/
│   ├── Dockerfile
│   ├── app.py              # REST API entry point
│   ├── requirements.txt
│   ├── ingestion/
│   │   ├── minio_client.py
│   │   ├── embedder.py     # Multimodal embedding logic
│   │   └── ttl.py          # 24h purge job
│   ├── retrieval/
│   │   └── retriever.py    # ChromaDB query wrapper
│   └── pipeline/
│       └── rag.py          # Prompt assembly + LLM call
│
├── models/
│   └── README.md           # Model download instructions
│
├── eval/
│   ├── eval_dataset.json   # Hand-annotated misogyny examples
│   └── evaluate.py         # Hit Rate, MRR, Precision@k
│
└── report/
    └── report.pdf
```

---

## Services (Docker Compose)

| Service | Image | Port | Purpose |
|---|---|---|---|
| `scraper` | custom | — | Bluesky polling + MinIO ingestion |
| `flask_app` | custom | 5000 | RAG API |
| `llm` | `ghcr.io/ggerganov/llama.cpp:server` | 8080 | Local LLM inference |
| `minio` | `minio/minio:latest` | 9000/9001 | Raw post object store |
| `chromadb` | `chromadb/chroma:latest` | 8001 | Vector search backend |

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/youruser/misogynai.git && cd misogynai

# 2. Download model weights
# Recommended: Llama-3.2-3B-Instruct-Q4_K_M.gguf (see models/README.md)
# Download from: https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF
 
# 3. Copy env
cp .env.example .env

# 4. Start everything
docker-compose up --build
```

API will be available at `http://localhost:5000`.

---

## API endpoints

### Query for misogynistic posts
```bash
curl -X POST http://localhost:5000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "posts insulting women in sport", "top_k": 5}'
```

### Get misogyny index stats
```bash
curl http://localhost:5000/stats
```

### Health check
```bash
curl http://localhost:5000/health
```

---

## Bluesky data model

Each scraped post is stored in MinIO as a JSON document with this structure:

```json
{
  "uri": "at://did:plc:xxx/app.bsky.feed.post/yyy",
  "cid": "bafyrei...",
  "author_did": "did:plc:xxx",
  "author_handle": "user.bsky.social",
  "text": "post content here",
  "created_at": "2026-03-16T10:00:00Z",
  "scraped_at": "2026-03-16T10:30:00Z",
  "images": [
    {
      "alt": "image alt text",
      "thumb_url": "https://cdn.bsky.app/..."
    }
  ],
  "langs": ["es", "en"],
  "labels": [],
  "like_count": 12,
  "repost_count": 3
}
```

---

## Embedding strategy

Posts are embedded as a single string combining text and image alt-texts:

```
[POST TEXT] {text} [IMAGE ALT] {alt_1} {alt_2}
```

Model: `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (multilingual, supports Spanish and English).

For image thumbnails (future): CLIP embeddings fused with text embeddings.

---

## TTL and data lifecycle

- Every 30 minutes: scraper runs, new posts ingested into MinIO + ChromaDB.
- On each ingestion cycle: posts with `scraped_at` older than 24 hours are deleted from both stores.
- ChromaDB metadata field `scraped_at_ts` (Unix timestamp) is used for TTL filtering.

---

## Evaluation

Retrieval quality is measured with:
- **Hit Rate @ k** (k ∈ {1, 3, 5})
- **Mean Reciprocal Rank (MRR)**
- **Precision @ k**

The evaluation dataset (`eval/eval_dataset.json`) contains hand-annotated misogynistic post examples.

---

## Known limitations

- Bluesky's public API rate limits scraping volume; not all posts can be captured.
- Misogyny labels in the evaluation dataset are manually assigned and may reflect annotator bias.
- The current embedding model is text-only; image content analysis is a planned extension.
- LLM inference on CPU (llama.cpp) is slow (~15–30 s/query); use a GPU instance for production.
- No authentication on the Flask API (add in production).

---

## Roadmap

- [ ] Fine-tuned misogyny binary classifier (HuggingFace)
- [ ] Rolling misogyny index chart in frontend
- [ ] CLIP multimodal embeddings for image posts
- [ ] Spanish-language optimised embedding model
- [ ] Alerting when misogyny index exceeds threshold
