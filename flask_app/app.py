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
        percentage_data = []
        misogynous_counts = []
        clean_counts = []
        
        for i in range(29, -1, -1):
            day_dt = datetime.now() - timedelta(days=i)
            day_str = day_dt.strftime("%Y-%m-%d")
            labels.append(day_str)
            
            day_start = day_str + "T00:00:00Z"
            day_end = day_str + "T23:59:59Z"
            
            # Aggregate: average score, count of misogynous (>0.5), count of clean (<=0.5)
            pipeline = [
                {"$match": {
                    "$or": [
                        {"created_at": {"$gte": day_start, "$lte": day_end}},
                        {"scraped_at": {"$gte": day_start, "$lte": day_end}}
                    ]
                }},
                {"$group": {
                    "_id": None,
                    "avg_score": {"$avg": "$misogyny_score"},
                    "misogynous_count": {"$sum": {"$cond": [{"$gt": ["$misogyny_score", 0.5]}, 1, 0]}},
                    "clean_count": {"$sum": {"$cond": [{"$lte": ["$misogyny_score", 0.5]}, 1, 0]}}
                }}
            ]
            agg_result = list(components["mongo"].collection.aggregate(pipeline))
            
            if agg_result and agg_result[0]:
                res = agg_result[0]
                avg_val = (res.get("avg_score") or 0.0) * 100
                percentage_data.append(round(avg_val, 2))
                misogynous_counts.append(res.get("misogynous_count") or 0)
                clean_counts.append(res.get("clean_count") or 0)
            else:
                percentage_data.append(0.0)
                misogynous_counts.append(0)
                clean_counts.append(0)
                
        return jsonify({
            "labels": labels,
            "percentage": percentage_data,
            "misogynous": misogynous_counts,
            "clean": clean_counts
        })
    except Exception as e:
        logger.error("history_stats_error", error=str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
