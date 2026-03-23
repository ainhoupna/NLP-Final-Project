import os
import sys
import time
import structlog
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from dotenv import load_dotenv
from openai import OpenAI

# Setup structured logging
logger = structlog.get_logger()

def load_mongodb():
    """Connects to MongoDB using connection string in env or fallback."""
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017/?directConnection=true")
    logger.info("connecting_mongodb", uri=mongo_uri)
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        return client["misogynai"]
    except ConnectionFailure as e:
        logger.error("mongodb_connection_failed", error=str(e))
        sys.exit(1)

def evaluate_posts(db):
    """
    Iterates over all posts in MongoDB that lack the 'qwen_misogyny' field.
    Uses the SGLang OpenAI compatible endpoint to assess whether the text is misogynistic.
    """
    # Point the OpenAI client to the local SGLang endpoint
    # Using the host network means we interact through 127.0.0.1:30000 within docker
    sglang_endpoint = os.environ.get("SGLANG_API_BASE", "http://127.0.0.1:30000/v1")
    client = OpenAI(
        base_url=sglang_endpoint,
        api_key="sk-no-key-required"
    )
    
    # Collection holding raw scraped posts
    collection = db["posts"]
    
    # Find all documents missing the 'qwen_misogyny' key
    query = {"qwen_misogyny": {"$exists": False}}
    total_unprocessed = collection.count_documents(query)
    logger.info("evaluation_started", unprocessed_posts=total_unprocessed)
    
    if total_unprocessed == 0:
        logger.info("evaluation_completed", message="No missing documents to process.")
        return

    cursor = collection.find(query)
    
    processed_count = 0
    errors_count = 0
    
    for doc in cursor:
        post_text = doc.get("text", "").strip()
        if not post_text:
            continue
            
        messages = [
            {
                "role": "system",
                "content": "You are an antisocial behavior analyst. You must evaluate whether the provided text constitutes misogyny. Reply ONLY with 'true' if the text is misogynistic, or 'false' if it is not."
            },
            {
                "role": "user",
                "content": post_text
            }
        ]
        
        try:
            chat_response = client.chat.completions.create(
                model="Qwen3.5-35B-A3B-Uncensored-HauhauCS-Aggressive", 
                messages=messages,
                max_tokens=10,
                temperature=0.1,
                top_p=0.8,
                presence_penalty=1.5,
                extra_body={
                    "top_k": 20,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            
            response_text = chat_response.choices[0].message.content.strip().lower()
            
            # Parse booleans
            if "true" in response_text:
                qwen_verdict = True
            elif "false" in response_text:
                qwen_verdict = False
            else:
                logger.warning("invalid_response_format", text=post_text, response=response_text)
                errors_count += 1
                continue
                
            # Update the document in MongoDB
            collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"qwen_misogyny": qwen_verdict}}
            )
            
            processed_count += 1
            if processed_count % 50 == 0:
                logger.info("evaluation_progress", processed=processed_count, total=total_unprocessed)
                
        except Exception as e:
            logger.error("qwen_api_error", post_id=str(doc.get("_id")), error=str(e))
            errors_count += 1
            # Sleep slightly on error to prevent crashing loop loop overload
            time.sleep(1)
            
    logger.info("evaluation_finished", processed=processed_count, errors=errors_count)

if __name__ == "__main__":
    load_dotenv()
    db = load_mongodb()
    evaluate_posts(db)
