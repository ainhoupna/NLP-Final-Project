"""Módulo de recuperación semántica de posts."""

from __future__ import annotations
import structlog
from ingestion.embedder import PostEmbedder

logger = structlog.get_logger()

class PostRetriever:
    """Recupera posts relevantes de ChromaDB usando búsqueda semántica."""

    def __init__(self, chroma_collection, embedder: PostEmbedder) -> None:
        """Inicializa el retriever."""
        self.collection = chroma_collection
        self.embedder = embedder

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Busca los posts más relevantes para la query dada."""
        try:
            logger.info("retrieving_posts", query=query, top_k=top_k)
            
            # 1. Generar embedding de la query
            query_vector = self.embedder.embed(query)
            
            # 2. Consultar ChromaDB
            results = self.collection.query(
                query_embeddings=[query_vector],
                n_results=top_k,
                include=["documents", "metadatas", "distances"]
            )
            
            # 3. Formatear resultados
            retrieved_posts = []
            
            # ChromaDB query results are lists of lists
            ids = results.get("ids", [[]])[0]
            docs = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]
            
            for i in range(len(ids)):
                # El score suele ser una distancia (más baja es mejor), 
                # calculamos una similitud aproximada para la UI
                score = 1.0 - distances[i] if i < len(distances) else 0.0
                
                retrieved_posts.append({
                    "uri": ids[i],
                    "text": docs[i],
                    "author_handle": metadatas[i].get("author_handle", "desconocido"),
                    "score": round(float(score), 4),
                    "created_at": metadatas[i].get("created_at"), # Podría no estar si no se normalizó así
                    "scraped_at_ts": metadatas[i].get("scraped_at_ts")
                })
            
            logger.info("retrieval_complete", count=len(retrieved_posts))
            return retrieved_posts
            
        except Exception as e:
            logger.error("retrieval_failed", error=str(e))
            return []
