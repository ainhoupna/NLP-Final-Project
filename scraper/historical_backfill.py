import os
import time
import structlog
from dotenv import load_dotenv

from bluesky_client import BlueskyClient
from ingestion.mongodb_client import MongoDBClient
from keywords import MISOGYNY_SEED_QUERIES

load_dotenv()
logger = structlog.get_logger()

def run_backfill(start_date: str, end_date: str):
    logger.info("starting_historical_backfill_mongo", start_date=start_date, end_date=end_date)
    
    bsky_client = BlueskyClient(
        handle=os.environ["BLUESKY_HANDLE"],
        app_password=os.environ["BLUESKY_APP_PASSWORD"]
    )
    bsky_client.login()

    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/?directConnection=true")
    MONGO_DB = os.getenv("MONGO_DB", "misogynai")
    MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "posts") # We can use the same collection or a different one

    mongo = MongoDBClient(MONGO_URI, MONGO_DB, MONGO_COLLECTION)
    mongo.ensure_indices("vector_index")

    # For historical backfill, we don't necessarily need embeddings immediately if we just want raw data,
    # but since the system expects them, we use the embedder.
    from ingestion.embedder import PostEmbedder
    embedder = PostEmbedder(os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))

    from models.predictor import MisogynyPredictor
    predictor = None
    CLASSIFIER_PATH = "/models/best_model.pth"
    if os.path.exists(CLASSIFIER_PATH):
        logger.info("loading_classifier_in_backfill", path=CLASSIFIER_PATH)
        predictor = MisogynyPredictor(CLASSIFIER_PATH)

    for query in MISOGYNY_SEED_QUERIES:
        logger.info("backfilling_query", query=query)
        cursor = None
        total_saved = 0
        
        while True:
            posts, next_cursor = bsky_client.search_posts_paginated(
                query=query,
                limit=100,
                since=start_date,
                until=end_date,
                cursor=cursor
            )
            
            if not posts:
                break
                
            for post in posts:
                # Generate embedding
                emb_text = embedder.build_embedding_text(post)
                vector = embedder.embed(emb_text)
                
                # Predict score
                score = 0.0
                if predictor:
                    score = predictor.predict_probability(post["text"])
                    
                mongo.upload_post(post, embedding=vector, misogyny_score=score)
                total_saved += 1
                
            logger.info("backfill_progress", query=query, saved_so_far=total_saved)
            
            if not next_cursor:
                break
                
            cursor = next_cursor
            time.sleep(2) 

    logger.info("historical_backfill_completed_mongo")

if __name__ == "__main__":
    # Get last 3 months to reach the 5000 quota
    START = "2024-12-01T00:00:00Z"
    END = "2025-02-01T00:00:00Z"
    run_backfill(START, END)
