# MisogynAI — Bluesky Misogyny RAG Monitor

[![Code Quality & Linting](https://github.com/ainhoupna/NLP-Final-Project/actions/workflows/lint.yml/badge.svg)](https://github.com/ainhoupna/NLP-Final-Project/actions/workflows/lint.yml)

> Real-time retrieval-augmented system for detecting and analysing misogynistic content on Bluesky Social.

---

## What this project does

This system continuously scrapes the Bluesky Social network via its public AT Protocol API every 30 minutes, stores raw posts in **MongoDB**, indexes them in multimodal embeddings, and exposes a RAG-powered REST API that lets you retrieve misogynistic posts by semantic query.

Beyond simple querying, the application features a **Multi-Agent Profiling System** powered by Llama-3 that evaluates user risk in real-time. By dynamically fetching a user's recent posts and parsing their live AT Protocol follow-graph, the Agents can detect deep psychological patterns, classify genuine vs sarcastic misogyny, and measure the toxicity of a user's echo chamber. All of this is visualized via a comprehensive web dashboard.

Posts older than 24 hours are automatically purged from both the vector store and the object store, keeping the index focused on the current state of the network.

---

## High-level architecture

```
Bluesky AT Protocol API
        |
        | (every 30 min, via APScheduler)
        v
  [ Scraper Service ]  ──►  **MongoDB** (raw posts)
        |
        v
  [ Ingestion Pipeline ]
    - Multimodal embedding (text + image alt-text)
    - ChromaDB indexing
    - TTL enforcement (delete posts > 24h)
        |
        v
  [ Flask REST & Web App ]
    POST /query                  ← semantic search for misogynistic posts
    GET  /stats                  ← misogyny index over time
    GET  /api/risk-monitor       ← user risk leaderboard
    GET  /api/agent-analyze-stream ← SSE multi-agent profile analysis
        |
        v
  [ AI Multi-Agent Pipeline ]  (Llama-3 via llama.cpp)
    - Agent 1: Stance Detection (Genuine vs Sarcastic/Denouncing)
    - Agent 2: Psychological Profiling (Hostile, Benevolent, Target Harassment)
    - Agent 3: Sociologist (Echo Chamber tracking via live AT Proto `getFollows` graph)
        |
        v
  [ Interactive Dashboard ]  (HTML/JS/Vanilla CSS)
    - RAG Search Interface
    - Risk Monitoring Leaderboards
    - Real-time SSE Agent Execution UI
```

---

## Repository structure (target)

```
misogynai/
├── docker-compose.yml
├── .env
├── LICENSE
├── README.md
│
├── scraper/
│   ├── Dockerfile
│   ├── scraper.py              # APScheduler + Loop de scraping
│   ├── bluesky_client.py       # Cliente AT Protocol (Firehose / feeds)
│   ├── historical_backfill.py  # Script para volcar históricos a BD
│   ├── keywords.py             # Diccionario de filtrado léxico
│   ├── requirements.txt
│   ├── ingestion/
│   │   ├── embedder.py         # Generación de Embeddings
│   │   ├── mongodb_client.py   # Conector oficial MongoDB
│   │   └── ttl.py              # Purgado de 24h
│   └── models/
│       ├── classifier.py
│       └── predictor.py
│
├── flask_app/
│   ├── Dockerfile
│   ├── app.py                  # API REST + Controladores
│   ├── requirements.txt
│   ├── static/
│   │   ├── css/style.css       # Estilos (Dashboard, Modales, Agent UI)
│   │   └── js/app.js           # Lógica SSE, Gráficas y Renderizado
│   ├── templates/
│   │   └── index.html          # Panel de Control principal
│   ├── ingestion/
│   │   ├── embedder.py
│   │   └── mongodb_client.py
│   ├── retrieval/
│   │   └── retriever.py        # Búsquedas semánticas (ChromaDB)
│   └── pipeline/
│       ├── rag.py              # Inferencia pregunta/respuesta
│       └── agent.py            # Orquestador Multi-Agente (Llama 3)
│
├── models/
│   ├── Meta-Llama-3-8B-Instruct.Q4_0.gguf    # Model LLM principal
│   ├── Llama-3.2-3B-Instruct-Q4_K_M.gguf
│   └── README.md
│
├── eval/
│   └── README.md               # Métricas de precisión @K
│
└── docs/
    └── ARCHITECTURE.md         # Documentación técnica extendida
```

---

## Services (Docker Compose)

| Service | Image | Port | Purpose |
|---|---|---|---|
| `scraper` | custom | — | Bluesky polling + MongoDB ingestion |
| `flask_app` | custom | 5000 | RAG API |
| `llm` | `ghcr.io/ggerganov/llama.cpp:server` | 8080 | Local LLM inference |
| `mongo` | `mongo:latest` | 27017 | Raw post database |

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

### Run Agent Analysis (SSE Stream)
```bash
curl "http://localhost:5000/api/agent-analyze-stream?handle=user.bsky.social"
```

### Get Risk Leaderboard
```bash
curl http://localhost:5000/api/risk-monitor
```

---

## Bluesky data model

Each scraped post is stored in **MongoDB** with this structure:

```json
{
  "uri": "at://did:plc:xxx/app.bsky.feed.post/yyy",
  "cid": "bafyrei...",
  "author_did": "did:plc:xxx",
  "author_handle": "user.bsky.social",
  "text": "post content here",
  "created_at": "2026-03-16T10:00:000Z",
  "scraped_at": "2026-03-16T10:30:000Z",
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

- Every 30 minutes: scraper runs, new posts ingested into **MongoDB** + ChromaDB.
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
- No authentication on the Flask API (add in production from now).

---

## Completed Project Roadmap

- [x] LLaMA-based Multi-Agent system for deep user profiling (Stance, Psychology, Sociology).
- [x] Real-time Dashboard UI with SSE streams and dynamic data visualization (Charts.js).
- [x] User Risk Leaderboard and Monitoring tabs.
- [x] Live API Context enhancement: falling back to `getAuthorFeed` for thin profiles, and `getFollows` graph traversal for echo-chamber calculations.
- [x] RAG querying with ChromaDB and MinIO TTL expirations.

Authors: Karim Abu Shams, Ainhoa Del Rey & Iñigo Goikoetxea
