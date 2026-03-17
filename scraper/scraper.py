"""Scraper principal de MisogynAI.

Orquesta el ciclo de scraping periódico: itera sobre las keywords semilla,
busca posts en Bluesky, los almacena en MinIO, los indexa en ChromaDB
y ejecuta la purga TTL de posts expirados.
"""

from __future__ import annotations
import os
import time
from datetime import datetime, timezone
import structlog
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler

import chromadb
from bluesky_client import BlueskyClient
from keywords import MISOGYNY_SEED_QUERIES
from ingestion.minio_client import MinIOClient
from ingestion.embedder import PostEmbedder
from ingestion.ttl import purge_expired_posts

# Configurar logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()

# Cargar variables de entorno
load_dotenv()

# --- Configuración ---
BSKY_HANDLE = os.getenv("BLUESKY_HANDLE")
BSKY_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD")

MINIO_URL = os.getenv("MINIO_URL", "127.0.0.1:9000")
MINIO_AK = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SK = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "posts")

CHROMA_HOST = os.getenv("CHROMADB_HOST", "127.0.0.1")
CHROMA_PORT = int(os.getenv("CHROMADB_PORT", 8000))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "bluesky_posts")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
INTERVAL = int(os.getenv("SCRAPE_INTERVAL_MINUTES", 30))
TTL_HOURS = int(os.getenv("POST_TTL_HOURS", 24))

# --- Inicialización de Clientes ---
bsky = BlueskyClient(BSKY_HANDLE, BSKY_PASSWORD)
minio = MinIOClient(MINIO_URL, MINIO_AK, MINIO_SK, MINIO_BUCKET)
embedder = PostEmbedder(EMBEDDING_MODEL)
chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

def run_scrape_cycle() -> None:
    """Ciclo completo de scraping."""
    logger.info("scrape_cycle_start")
    
    try:
        # 0. Asegurar infraestructura
        minio.ensure_bucket()
        collection = chroma_client.get_or_create_collection(name=CHROMA_COLLECTION)
        
        # 1. Login Bluesky
        bsky.login()
        
        total_ingested = 0
        
        # 2. Iterar sobre keywords
        for query in MISOGYNY_SEED_QUERIES:
            logger.info("searching_query", query=query)
            posts = bsky.search_posts(query, limit=50)
            
            for post in posts:
                try:
                    # 3. Almacenar en MinIO
                    minio_key = minio.upload_post(post)
                    
                    # 4. Enriquecer post con metadata de sistema
                    post["minio_key"] = minio_key
                    scraped_at_dt = datetime.fromisoformat(post["scraped_at"])
                    post["scraped_at_ts"] = scraped_at_dt.timestamp()
                    
                    # 5. Generar embedding
                    emb_text = embedder.build_embedding_text(post)
                    vector = embedder.embed(emb_text)
                    
                    # 6. Indexar en ChromaDB
                    # Simplificamos los metadatos para Chroma (solo tipos básicos)
                    metadata = {
                        "uri": post["uri"],
                        "author_handle": post["author_handle"],
                        "minio_key": minio_key,
                        "scraped_at_ts": post["scraped_at_ts"],
                        "like_count": post["like_count"],
                        "repost_count": post["repost_count"]
                    }
                    
                    collection.add(
                        ids=[post["uri"]],
                        embeddings=[vector],
                        metadatas=[metadata],
                        documents=[post["text"]]
                    )
                    total_ingested += 1
                    
                except Exception as e:
                    logger.error("post_ingestion_error", uri=post.get("uri"), error=str(e))
                    continue
        
        logger.info("ingestion_complete", total=total_ingested)
        
        # 7. Purga TTL
        deleted = purge_expired_posts(collection, minio, TTL_HOURS)
        logger.info("scrape_cycle_end", ingested=total_ingested, purged=deleted)
        
    except Exception as e:
        logger.error("scrape_cycle_failed", error=str(e))

def start_scheduler() -> None:
    """Configura APScheduler para ejecutar periodicamente."""
    scheduler = BlockingScheduler()
    scheduler.add_job(run_scrape_cycle, 'interval', minutes=INTERVAL, next_run_time=datetime.now())
    
    logger.info("scheduler_started", interval_minutes=INTERVAL)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    start_scheduler()
