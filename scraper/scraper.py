import os
import time
from datetime import datetime, timedelta, timezone
import structlog
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler

from bluesky_client import BlueskyClient
from keywords import MISOGYNY_SEED_QUERIES
from ingestion.mongodb_client import MongoDBClient
from ingestion.embedder import PostEmbedder
from ingestion.ttl import purge_expired_posts_mongo
from qwen_evaluator import evaluate_posts

def cleanup_old_posts(mongo: MongoDBClient, days: int = 180):
    """Deletes posts older than 180 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    res = mongo.collection.delete_many({
        "$and": [
            {"created_at": {"$lt": cutoff}},
            {"scraped_at": {"$lt": cutoff}}
        ]
    })
    return res.deleted_count

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

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/?directConnection=true")
MONGO_DB = os.getenv("MONGO_DB", "misogynai")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "posts")
MONGO_VECTOR_INDEX = os.getenv("MONGO_VECTOR_INDEX", "vector_index")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
INTERVAL = int(os.getenv("SCRAPE_INTERVAL_MINUTES", 30))
TTL_HOURS = int(os.getenv("POST_TTL_HOURS", 24))

# --- Inicialización de Clientes ---
bsky = BlueskyClient(BSKY_HANDLE, BSKY_PASSWORD)
mongo = MongoDBClient(MONGO_URI, MONGO_DB, MONGO_COLLECTION)
embedder = PostEmbedder(EMBEDDING_MODEL)

def run_scrape_cycle() -> None:
    """Ciclo completo de scraping."""
    logger.info("scrape_cycle_start")
    
    try:
        # Periodically remove posts older than 6 months
        deleted = cleanup_old_posts(mongo, days=180)
        if deleted > 0:
            logger.info("retention_cleanup_performed", deleted_count=deleted)

        # 0. Asegurar infraestructura
        mongo.ensure_indices(MONGO_VECTOR_INDEX)
        
        # 1. Login Bluesky
        bsky.login()
        
        # --- Predictor ---
        from models.predictor import MisogynyPredictor
        predictor = None
        if os.path.exists("/models/best_model.pth"):
            predictor = MisogynyPredictor("/models/best_model.pth")

        total_ingested = 0
        
        # 2. Iterar sobre keywords
        for query in MISOGYNY_SEED_QUERIES:
            logger.info("searching_query", query=query)
            posts = bsky.search_posts(query, limit=50)
            
            for post in posts:
                try:
                    # 3. Generar embedding
                    emb_text = embedder.build_embedding_text(post)
                    vector = embedder.embed(emb_text)
                    
                    # 4. Calcular score
                    score = 0.0
                    if predictor:
                        score = predictor.predict_probability(post["text"])
                    
                    # 5. Almacenar con score
                    mongo.upload_post(post, embedding=vector, misogyny_score=score)
                    
                    total_ingested += 1
                except Exception as e:
                    logger.error("post_ingestion_error", uri=post.get("uri"), error=str(e))
                    continue
        
        logger.info("ingestion_complete", total=total_ingested)
        
        # 5. Long-term retention is already handled by cleanup_old_posts at the start of cycle
        logger.info("scrape_cycle_end", ingested=total_ingested)
        
        # 6. Evaluate new posts with Qwen (Self-contained)
        logger.info("starting_qwen_evaluation")
        evaluate_posts(mongo.db)
        logger.info("qwen_evaluation_done")
        
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
    run_scrape_cycle() # Run once at startup
    start_scheduler()
