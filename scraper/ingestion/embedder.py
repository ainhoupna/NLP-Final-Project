"""Módulo de generación de embeddings para posts."""

from __future__ import annotations
import structlog
from sentence_transformers import SentenceTransformer

logger = structlog.get_logger()

class PostEmbedder:
    """Genera embeddings para posts usando sentence-transformers."""

    def __init__(self, model_name: str) -> None:
        """Inicializa el embedder con el modelo indicado."""
        logger.info("loading_embedding_model", model=model_name)
        self.model = SentenceTransformer(model_name)
        logger.info("embedding_model_loaded")

    def build_embedding_text(self, post: dict) -> str:
        """Combina text + alt-texts de imágenes en un solo string para embedding.
        
        Formato: [POST TEXT] {text} [IMAGE ALT] {alt_1} {alt_2} ...
        """
        text = post.get("text", "")
        images = post.get("images", [])
        
        parts = [f"[POST TEXT] {text}"]
        if images:
            parts.append("[IMAGE ALT]")
            parts.extend(images)
            
        return " ".join(parts)

    def embed(self, text: str) -> list[float]:
        """Genera el embedding de un texto."""
        try:
            embedding = self.model.encode(text)
            return embedding.tolist()
        except Exception as e:
            logger.error("embedding_failed", error=str(e))
            raise

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings para un lote de textos."""
        try:
            embeddings = self.model.encode(texts)
            return embeddings.tolist()
        except Exception as e:
            logger.error("batch_embedding_failed", error=str(e))
            raise
