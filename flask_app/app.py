import os
import structlog
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from datetime import datetime, timedelta

from ingestion.embedder import PostEmbedder
from ingestion.mongodb_client import MongoDBClient
from retrieval.retriever import PostRetriever
from pipeline.rag import run_rag
from models.predictor import MisogynyPredictor

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

app = Flask(__name__)

# --- Componentes (Singletons) ---
components = {
    "embedder": None,
    "mongo": None,
    "retriever": None,
    "predictor": None
}

def _initialize_components():
    """Inicializa los clientes de servicios externos."""
    try:
        MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/?directConnection=true")
        MONGO_DB = os.getenv("MONGO_DB", "misogynai")
        MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "posts")
        MONGO_VECTOR_INDEX = os.getenv("MONGO_VECTOR_INDEX", "vector_index")

        LLM_URL = os.getenv("LLM_URL", "http://127.0.0.1:8080")
        EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
        CLASSIFIER_WS = "/models/best_model.pth"

        logger.info("initializing_components_mongo")

        components["embedder"] = PostEmbedder(EMBEDDING_MODEL)
        components["mongo"] = MongoDBClient(MONGO_URI, MONGO_DB, MONGO_COLLECTION)
        components["mongo"].ensure_indices(MONGO_VECTOR_INDEX)
        
        components["retriever"] = PostRetriever(components["mongo"], components["embedder"], MONGO_VECTOR_INDEX)
        components["llm_url"] = LLM_URL

        # Cargar el clasificador de misoginia (PyTorch)
        if os.path.exists(CLASSIFIER_WS):
            logger.info("loading_classifier", path=CLASSIFIER_WS)
            components["predictor"] = MisogynyPredictor(CLASSIFIER_WS)
        else:
            logger.warning("classifier_not_found", path=CLASSIFIER_WS)

        logger.info("components_initialized_successfully")

    except Exception as e:
        logger.error("initialization_failed", error=str(e))
        raise

# Intentar inicializar al arrancar la app
try:
    _initialize_components()
except Exception:
    print("Warning: Components not implemented or services down. Starting API only.")

@app.route("/")
def index():
    """Sirve el dashboard principal."""
    return render_template("index.html")

@app.route("/query", methods=["POST"])
def query():
    """Endpoint para consultas RAG."""
    data = request.json
    question = data.get("question")
    top_k = data.get("top_k", 5)

    if not question:
        return jsonify({"error": "No question provided"}), 400

    if not components["retriever"]:
        return jsonify({"error": "System components not initialized"}), 503

    try:
        logger.info("handling_query", question=question)
        result = run_rag(question, components["retriever"], components["llm_url"], top_k=top_k)
        return jsonify(result)
    except Exception as e:
        logger.error("query_handler_error", error=str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/stats", methods=["GET"])
def stats():
    """Devuelve estadísticas del sistema."""
    if not components["mongo"]:
        return jsonify({"error": "System not initialized"}), 503

    try:
        mongo_stats = components["mongo"].get_stats()
        
        return jsonify({
            "status": "online",
            "indexed_posts": mongo_stats["count"],
            "storage": "mongodb",
            "llm_status": "ready" 
        })
    except Exception as e:
        logger.error("stats_handler_error", error=str(e))
        return jsonify({"status": "degraded", "error": str(e)}), 500

@app.route("/stats/history", methods=["GET"])
def history_stats():
    """Returns time series data (percentage and volume) for the last 30 days."""
    if not components["mongo"]:
        return jsonify({"error": "MongoDB not available"}), 503
    
    try:
        labels = []
        avg_scores = []
        misogynous_counts = []
        clean_counts = []
        
        # Calculate cutoff (180 days ago)
        cutoff_dt = datetime.now() - timedelta(days=179)
        cutoff_str = cutoff_dt.strftime("%Y-%m-%d") + "T00:00:00Z"
        
        pipeline = [
            {"$match": {
                "created_at": {"$gte": cutoff_str}
            }},
            {"$project": {
                "day": {"$substr": ["$created_at", 0, 10]},
                "misogyny_score": 1
            }},
            {"$group": {
                "_id": "$day",
                "avg_score": {"$avg": "$misogyny_score"},
                "misogynous_count": {"$sum": {"$cond": [{"$gt": ["$misogyny_score", 0.5]}, 1, 0]}},
                "clean_count": {"$sum": {"$cond": [{"$lte": ["$misogyny_score", 0.5]}, 1, 0]}}
            }},
            {"$sort": {"_id": 1}}
        ]
        
        results = list(components["mongo"].collection.aggregate(pipeline))
        result_map = {r["_id"]: r for r in results}
        
        # Fill in gaps to ensure a continuous timeline
        for i in range(179, -1, -1):
            day_dt = datetime.now() - timedelta(days=i)
            day_str = day_dt.strftime("%Y-%m-%d")
            labels.append(day_str)
            
            if day_str in result_map:
                r = result_map[day_str]
                avg_scores.append(round((r.get("avg_score") or 0.0) * 100, 2))
                misogynous_counts.append(r.get("misogynous_count") or 0)
                clean_counts.append(r.get("clean_count") or 0)
            else:
                avg_scores.append(0.0)
                misogynous_counts.append(0)
                clean_counts.append(0)
                
        return jsonify({
            "labels": labels,
            "percentage": avg_scores,
            "misogynous": misogynous_counts,
            "clean": clean_counts
        })
    except Exception as e:
        logger.error("history_stats_error", error=str(e))
        return jsonify({"error": str(e)}), 500
@app.route("/stats/risky-users", methods=["GET"])
def risky_users():
    """Identifies top 15 users with high misogyny scores."""
    if not components["mongo"]:
        return jsonify({"error": "MongoDB not available"}), 503
    
    try:
        pipeline = [
            {"$match": {"misogyny_score": {"$gt": 0.5}}},
            {"$group": {
                "_id": "$author_handle",
                "total_misogynistic_posts": {"$sum": 1},
                "avg_score": {"$avg": "$misogyny_score"},
                "max_score": {"$max": "$misogyny_score"},
                "author_did": {"$first": "$author_did"}
            }},
            {"$addFields": {
                "risk_score": {"$multiply": ["$total_misogynistic_posts", "$avg_score"]}
            }},
            {"$sort": {"risk_score": -1}},
            {"$limit": 15}
        ]
        
        results = list(components["mongo"].collection.aggregate(pipeline))
        return jsonify(results)
    except Exception as e:
        logger.error("risky_users_error", error=str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/api/user-posts/<handle>", methods=["GET"])
def user_posts(handle):
    """Fetches detailed misogynistic posts for a specific user."""
    if not components["mongo"]:
        return jsonify({"error": "MongoDB not available"}), 503
    
    try:
        # Get posts
        posts = list(components["mongo"].collection.find(
            {"author_handle": handle, "misogyny_score": {"$gt": 0.5}},
            {"text": 1, "created_at": 1, "misogyny_score": 1, "_id": 0}
        ).sort("created_at", -1).limit(20))
        
        # Get user summary from all their posts (not just misogynistic)
        stats_pipeline = [
            {"$match": {"author_handle": handle}},
            {"$group": {
                "_id": "$author_handle",
                "total_posts": {"$sum": 1},
                "misogynous_posts": {"$sum": {"$cond": [{"$gt": ["$misogyny_score", 0.5]}, 1, 0]}},
                "avg_misogyny": {"$avg": "$misogyny_score"}
            }}
        ]
        stats_list = list(components["mongo"].collection.aggregate(stats_pipeline))
        summary = stats_list[0] if stats_list else {}
        
        return jsonify({
            "handle": handle,
            "posts": posts,
            "summary": summary
        })
    except Exception as e:
        logger.error("user_posts_error", handle=handle, error=str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
