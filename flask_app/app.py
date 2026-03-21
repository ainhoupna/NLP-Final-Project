import os
import json
import structlog
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
from datetime import datetime, timedelta

from ingestion.embedder import PostEmbedder
from ingestion.mongodb_client import MongoDBClient
from retrieval.retriever import PostRetriever
from pipeline.rag import run_rag
from pipeline.agent import run_agent_analysis
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
        total_posts = mongo_stats["count"]
        
        # Calculate toxicity rate
        toxic_posts = components["mongo"].collection.count_documents({"misogyny_score": {"$gt": 0.5}})
        toxicity_rate = round((toxic_posts / total_posts) * 100, 1) if total_posts > 0 else 0
        
        # Calculate unique profiles monitored
        profiles = len(components["mongo"].collection.distinct("author_handle"))
        
        return jsonify({
            "status": "online",
            "indexed_posts": total_posts,
            "profiles_monitored": profiles,
            "toxicity_rate": f"{toxicity_rate}%"
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

@app.route("/stats/history-hourly", methods=["GET"])
def history_stats_hourly():
    """Returns time series data (percentage and volume) for the last 72 hours."""
    if not components["mongo"]:
        return jsonify({"error": "MongoDB not available"}), 503
    
    try:
        labels = []
        avg_scores = []
        misogynous_counts = []
        clean_counts = []
        
        # Calculate cutoff (72 hours ago)
        cutoff_dt = datetime.now() - timedelta(hours=71)
        cutoff_str = cutoff_dt.strftime("%Y-%m-%dT%H:00:00Z")
        
        pipeline = [
            {"$match": {
                "created_at": {"$gte": cutoff_str}
            }},
            {"$project": {
                "hour": {"$substr": ["$created_at", 0, 13]}, # "YYYY-MM-DDTHH"
                "misogyny_score": 1
            }},
            {"$group": {
                "_id": "$hour",
                "avg_score": {"$avg": "$misogyny_score"},
                "misogynous_count": {"$sum": {"$cond": [{"$gt": ["$misogyny_score", 0.5]}, 1, 0]}},
                "clean_count": {"$sum": {"$cond": [{"$lte": ["$misogyny_score", 0.5]}, 1, 0]}}
            }},
            {"$sort": {"_id": 1}}
        ]
        
        results = list(components["mongo"].collection.aggregate(pipeline))
        result_map = {r["_id"]: r for r in results}
        
        # Fill in gaps to ensure a continuous timeline
        for i in range(71, -1, -1):
            hour_dt = datetime.now() - timedelta(hours=i)
            # Match the substr format: YYYY-MM-DDTHH
            hour_str_match = hour_dt.strftime("%Y-%m-%dT%H")
            # Presentable label: HH:00
            hour_label = hour_dt.strftime("%H:00")
            
            labels.append(hour_label)
            
            if hour_str_match in result_map:
                r = result_map[hour_str_match]
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
        logger.error("history_stats_hourly_error", error=str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/api/monitoring/posts-by-time", methods=["GET"])
def monitoring_posts_by_time():
    """Fetches high-risk posts for a specific time label (day or hour)."""
    if not components["mongo"]:
        return jsonify({"error": "MongoDB not available"}), 503
    
    time_label = request.args.get("time_label")
    mode = request.args.get("mode", "72h") # '72h' means hour, '180d' means day
    
    if not time_label:
        return jsonify({"error": "Missing time_label parameter"}), 400
        
    try:
        if mode == "72h":
            # We need to find the specific hour in the last 72h that matches this
            # Because "14:00" might happen three times in 72h,
            # we check the last 72 hours for matching hours.
            now = datetime.now()
            target_hour_str = time_label.split(":")[0] # "14"
            
            # Find the most recent date-time in the last 72h that matches the hour
            found_dt_start = None
            found_dt_end = None
            
            # Walk backwards from today, up to 3 days (72h)
            # but constrained to the last 72 hours to be safe.
            cutoff_dt = now - timedelta(hours=72)
            cutoff_str = cutoff_dt.strftime("%Y-%m-%dT%H:00:00Z")
            
            query = {
                "created_at": {"$gte": cutoff_str, "$regex": f"T{target_hour_str}:"},
                "misogyny_score": {"$gt": 0.5}
            }
        else:
            # time_label is like "2026-03-21"
            query = {
                "created_at": {"$regex": f"^{time_label}"},
                "misogyny_score": {"$gt": 0.5}
            }
            
        posts = list(components["mongo"].collection.find(
            query,
            {"text": 1, "created_at": 1, "misogyny_score": 1, "author_handle": 1, "_id": 0}
        ).sort("misogyny_score", -1).limit(50))
        
        return jsonify({"posts": posts})
        
    except Exception as e:
        logger.error("monitoring_posts_by_time_error", error=str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/stats/decomposition", methods=["GET"])
def decomposition_stats():
    """Additive time series decomposition: trend (7-day MA), seasonality, residuals."""
    if not components["mongo"]:
        return jsonify({"error": "MongoDB not available"}), 503
    
    try:
        cutoff_dt = datetime.now() - timedelta(days=179)
        cutoff_str = cutoff_dt.strftime("%Y-%m-%d") + "T00:00:00Z"
        
        pipeline = [
            {"$match": {"created_at": {"$gte": cutoff_str}}},
            {"$project": {
                "day": {"$substr": ["$created_at", 0, 10]},
                "misogyny_score": 1
            }},
            {"$group": {
                "_id": "$day",
                "avg_score": {"$avg": "$misogyny_score"}
            }},
            {"$sort": {"_id": 1}}
        ]
        
        results = list(components["mongo"].collection.aggregate(pipeline))
        result_map = {r["_id"]: round((r.get("avg_score") or 0) * 100, 2) for r in results}
        
        # Build continuous daily series
        labels = []
        original = []
        for i in range(179, -1, -1):
            day_dt = datetime.now() - timedelta(days=i)
            day_str = day_dt.strftime("%Y-%m-%d")
            labels.append(day_str)
            original.append(result_map.get(day_str, 0.0))
        
        n = len(original)
        window = 7
        
        # 1) Trend: centered 7-day moving average
        trend = [None] * n
        half = window // 2
        for i in range(half, n - half):
            trend[i] = round(sum(original[i - half:i + half + 1]) / window, 2)
        
        # 2) Detrended = original - trend
        detrended = [None] * n
        for i in range(n):
            if trend[i] is not None:
                detrended[i] = round(original[i] - trend[i], 2)
        
        # 3) Seasonality: average detrended value per day-of-week (period=7)
        from collections import defaultdict
        dow_sums = defaultdict(list)
        for i in range(n):
            if detrended[i] is not None:
                day_dt = datetime.now() - timedelta(days=179 - i)
                dow = day_dt.weekday()  # 0=Mon ... 6=Sun
                dow_sums[dow].append(detrended[i])
        
        dow_avg = {}
        for dow, vals in dow_sums.items():
            dow_avg[dow] = round(sum(vals) / len(vals), 2) if vals else 0.0
        
        seasonal = [None] * n
        for i in range(n):
            day_dt = datetime.now() - timedelta(days=179 - i)
            dow = day_dt.weekday()
            seasonal[i] = dow_avg.get(dow, 0.0)
        
        # 4) Residuals = original - trend - seasonal
        residuals = [None] * n
        for i in range(n):
            if trend[i] is not None:
                residuals[i] = round(original[i] - trend[i] - seasonal[i], 2)
        
        return jsonify({
            "labels": labels,
            "original": original,
            "trend": trend,
            "seasonal": seasonal,
            "residuals": residuals
        })
    except Exception as e:
        logger.error("decomposition_stats_error", error=str(e))
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


@app.route("/stats/risky-users-diverse", methods=["GET"])
def risky_users_diverse():
    """Identifies top 15 users ranked by UNIQUE misogynistic content diversity."""
    if not components["mongo"]:
        return jsonify({"error": "MongoDB not available"}), 503
    
    try:
        pipeline = [
            {"$match": {"misogyny_score": {"$gt": 0.5}}},
            {"$group": {
                "_id": "$author_handle",
                "total_misogynistic_posts": {"$sum": 1},
                "unique_texts": {"$addToSet": "$text"},
                "avg_score": {"$avg": "$misogyny_score"},
                "max_score": {"$max": "$misogyny_score"},
                "author_did": {"$first": "$author_did"}
            }},
            {"$addFields": {
                "unique_count": {"$size": "$unique_texts"},
                "diversity_ratio": {
                    "$cond": [
                        {"$gt": ["$total_misogynistic_posts", 0]},
                        {"$round": [{"$multiply": [
                            {"$divide": [{"$size": "$unique_texts"}, "$total_misogynistic_posts"]},
                            100
                        ]}, 1]},
                        0
                    ]
                }
            }},
            {"$addFields": {
                "diversity_score": {"$multiply": [{"$size": "$unique_texts"}, "$avg_score"]}
            }},
            {"$project": {"unique_texts": 0}},
            {"$sort": {"diversity_score": -1}},
            {"$limit": 15}
        ]
        
        results = list(components["mongo"].collection.aggregate(pipeline))
        return jsonify(results)
    except Exception as e:
        logger.error("risky_users_diverse_error", error=str(e))
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

@app.route("/api/agent-analyze", methods=["POST"])
def agent_analyze():
    """Runs the agent to deeply analyze a user profile (Non-streaming)."""
    if not components["mongo"]:
        return jsonify({"error": "MongoDB not available"}), 503
    
    data = request.json
    handle = data.get("handle", "").strip().lstrip("@")
    
    if not handle:
        return jsonify({"error": "No handle provided"}), 400
    
    try:
        logger.info("agent_analyze_request", handle=handle)
        result = run_agent_analysis(
            handle=handle,
            mongo_collection=components["mongo"].collection,
            llm_url=components.get("llm_url", "http://127.0.0.1:8080")
        )
        return jsonify(result)
    except Exception as e:
        logger.error("agent_analyze_error", handle=handle, error=str(e))
        return jsonify({"error": str(e)}), 500

from flask import Response, stream_with_context

@app.route("/api/agent-analyze-stream")
def agent_analyze_stream():
    """Streams agent analysis progress using Server-Sent Events (SSE)."""
    if not components["mongo"]:
        return Response("data: {\"error\": \"MongoDB not available\"}\n\n", mimetype="text/event-stream"), 503
        
    handle = request.args.get("handle", "").strip().lstrip("@")
    if not handle:
        return Response("data: {\"error\": \"No handle provided\"}\n\n", mimetype="text/event-stream"), 400

    logger.info("agent_analyze_stream_request", handle=handle)
    mongo_coll = components["mongo"].collection
    llm_url = components.get("llm_url", "http://127.0.0.1:8080")

    def generate():
        try:
            from pipeline.agent import run_agent_analysis_stream
            for event in run_agent_analysis_stream(handle, mongo_coll, llm_url):
                # SSE Format: "data: <string>\n\n"
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.error("agent_stream_error", handle=handle, error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
