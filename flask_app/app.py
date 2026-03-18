"""API de MisogynAI.

Proporciona endpoints para consultas RAG y estadísticas del sistema.
"""

from __future__ import annotations
import os
import structlog
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

import chromadb
from ingestion.embedder import PostEmbedder
from ingestion.minio_client import MinIOClient
from retrieval.retriever import PostRetriever
from pipeline.rag import run_rag

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
    "minio": None,
    "retriever": None,
    "chroma_client": None,
    "chroma_collection": None
}

def _initialize_components():
    """Inicializa los clientes de servicios externos."""
    try:
        MINIO_URL = os.getenv("MINIO_URL", "127.0.0.1:9000")
        MINIO_AK = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        MINIO_SK = os.getenv("MINIO_SECRET_KEY", "minioadmin")
        MINIO_BUCKET = os.getenv("MINIO_BUCKET", "posts")

        CHROMA_HOST = os.getenv("CHROMADB_HOST", "127.0.0.1")
        CHROMA_PORT = int(os.getenv("CHROMADB_PORT", 8000))
        CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "bluesky_posts")

        LLM_URL = os.getenv("LLM_URL", "http://127.0.0.1:8080")
        EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")

        logger.info("initializing_components")

        components["embedder"] = PostEmbedder(EMBEDDING_MODEL)
        
        components["minio"] = MinIOClient(MINIO_URL, MINIO_AK, MINIO_SK, MINIO_BUCKET)
        components["minio.url"] = MINIO_URL # For stats
        
        MINIO_HISTORY_BUCKET = os.getenv("MINIO_HISTORY_BUCKET", "history")
        components["minio_history"] = MinIOClient(MINIO_URL, MINIO_AK, MINIO_SK, MINIO_HISTORY_BUCKET)
        
        components["chroma_client"] = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        components["chroma_collection"] = components["chroma_client"].get_or_create_collection(name=CHROMA_COLLECTION)
        
        components["retriever"] = PostRetriever(components["chroma_collection"], components["embedder"])
        components["llm_url"] = LLM_URL

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
    if not components["chroma_collection"]:
        return jsonify({"error": "System not initialized"}), 503

    try:
        post_count = components["chroma_collection"].count()
        
        return jsonify({
            "status": "online",
            "indexed_posts": post_count,
            "minio_bucket": os.getenv("MINIO_BUCKET", "posts"),
            "llm_status": "ready" 
        })
    except Exception as e:
        logger.error("stats_handler_error", error=str(e))
        return jsonify({"status": "degraded", "error": str(e)}), 500

@app.route("/stats/history", methods=["GET"])
def history_stats():
    """Devuelve la serie temporal de misoginia (Mock hasta modelo de ML)."""
    import datetime
    import random
    
    # Generamos datos mock para los últimos 7 días
    today = datetime.date.today()
    labels = [(today - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    # Simula un porcentaje de misoginia entre 10% y 40%
    data = [random.uniform(10.0, 40.0) for _ in range(7)]
    
    return jsonify({
        "labels": labels,
        "datasets": [{
            "label": "% Misoginia (Simulado)",
            "data": [round(val, 2) for val in data]
        }]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
