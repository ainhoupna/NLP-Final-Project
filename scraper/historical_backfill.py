import os
import time
import structlog
from dotenv import load_dotenv

from bluesky_client import BlueskyClient
from ingestion.mongodb_client import MongoDBClient
from keywords import MISOGYNY_SEED_QUERIES

load_dotenv()
logger = structlog.get_logger()

from datetime import datetime, timedelta, timezone

def cleanup_old_posts(mongo: MongoDBClient, days: int = 180):
    """Deletes posts older than the specified number of days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    # Delete posts where created_at OR scraped_at is older than cutoff
    res = mongo.collection.delete_many({
        "$or": [
            {"created_at": {"$lt": cutoff}},
            {"scraped_at": {"$lt": cutoff}}
        ]
    })
    logger.info("retention_cleanup_completed", deleted_count=res.deleted_count, cutoff=cutoff)

def run_backfill(days_back: int = 180):
    logger.info("starting_historical_backfill_mongo", days_back=days_back)
    
    bsky_client = BlueskyClient(
        handle=os.environ["BLUESKY_HANDLE"],
        app_password=os.environ["BLUESKY_APP_PASSWORD"]
    )
    bsky_client.login()

    MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/?directConnection=true")
    MONGO_DB = os.getenv("MONGO_DB", "misogynai")
    MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "posts")

    mongo = MongoDBClient(MONGO_URI, MONGO_DB, MONGO_COLLECTION)
    
    # 1. Cleanup old data
    cleanup_old_posts(mongo, days=days_back)

    from ingestion.embedder import PostEmbedder
    embedder = PostEmbedder(os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))

    from models.predictor import MisogynyPredictor
    predictor = None
    CLASSIFIER_PATH = "/models/best_model.pth"
    if os.path.exists(CLASSIFIER_PATH):
        predictor = MisogynyPredictor(CLASSIFIER_PATH)

    # 2. Backfill loop per day to ensure coverage (Yesterday -> 180 days ago)
    for i in range(61, days_back + 1):  # Resume from Jan 18, 2026
        target_dt = datetime.now(timezone.utc) - timedelta(days=i)
        target_day = target_dt.strftime("%Y-%m-%d")
        next_day = (target_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        
        start_date = f"{target_day}T00:00:00Z"
        end_date = f"{next_day}T00:00:00Z"
        
        logger.info("backfilling_day_start", day=target_day, until=end_date, days_ago=i)
        
        for query in MISOGYNY_SEED_QUERIES:
            cursor = None
            day_saved = 0
            while day_saved < 100: # Target ~100 per query per day to spread data
                batch, next_cursor = bsky_client.search_posts_paginated(
                    query=query,
                    limit=50,
                    since=start_date,
                    until=end_date,
                    cursor=cursor
                )
                if not batch: break
                    
                for post in batch:
                    # CLIENT-SIDE VALIDATION: Skip if the post is not from the target day
                    # This protects against indexer noise or ignored filters
                    if post["created_at"] and not post["created_at"].startswith(target_day):
                        continue
                        
                    emb_text = embedder.build_embedding_text(post)
                    vector = embedder.embed(emb_text)
                    score = predictor.predict_probability(post["text"]) if predictor else 0.0
                    mongo.upload_post(post, embedding=vector, misogyny_score=score)
                    day_saved += 1
                
                if not next_cursor: break
                cursor = next_cursor
                time.sleep(2) # Throttle between pages
            
            time.sleep(5) # Throttle between different queries
        
        time.sleep(10) # Throttle between days

    logger.info("historical_backfill_completed_mongo")

if __name__ == "__main__":
    run_backfill(180) # 6 months
