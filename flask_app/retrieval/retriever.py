from __future__ import annotations
import structlog
from ingestion.embedder import PostEmbedder
from ingestion.mongodb_client import MongoDBClient

logger = structlog.get_logger()

class PostRetriever:
    """Recupera posts relevantes de MongoDB usando búsqueda semántica."""

    def __init__(self, mongo_client: MongoDBClient, embedder: PostEmbedder, vector_index: str = "vector_index") -> None:
        """Inicializa el retriever."""
        self.mongo = mongo_client
        self.embedder = embedder
        self.vector_index = vector_index

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Busca los posts más relevantes para la query dada."""
        try:
            logger.info("retrieving_posts_mongo", query=query, top_k=top_k)
            
            # 1. Generar embedding de la query (alineado con formato de indexación)
            formatted_query = f"[POST TEXT] {query}"
            query_vector = self.embedder.embed(formatted_query)
            
            # 2. Consultar MongoDB usando Vector Search
            results = self.mongo.vector_search(
                embedding=query_vector,
                limit=top_k,
                index_name=self.vector_index
            )
            
            # 3. Formatear resultados
            retrieved_posts = []
            
            for doc in results:
                # Calculamos una similitud aproximada si existe el score de Atlas
                # Atlas Search suele devolver un score en metadata o como un campo
                score = doc.get("$vectorSearchScore", 0.0)
                
                retrieved_posts.append({
                    "uri": doc["uri"],
                    "text": doc["text"],
                    "author_handle": doc.get("author_handle", "desconocido"),
                    "score": round(float(score), 4),
                    "created_at": doc.get("created_at"),
                    "scraped_at": doc.get("scraped_at")
                })
            
            logger.info("retrieval_complete", count=len(retrieved_posts))
            return retrieved_posts
            
        except Exception as e:
            logger.error("retrieval_failed", error=str(e))
            return []
