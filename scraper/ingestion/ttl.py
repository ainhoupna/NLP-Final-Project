"""Gestión del TTL (Time-To-Live) de posts."""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
import structlog
from .minio_client import MinIOClient

logger = structlog.get_logger()

def purge_expired_posts(
    chroma_collection,
    minio_client: MinIOClient,
    ttl_hours: int = 24,
) -> int:
    """Elimina posts con scraped_at_ts anterior al umbral de TTL."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        cutoff_ts = cutoff.timestamp()
        
        logger.info("starting_ttl_purge", cutoff=cutoff.isoformat(), ttl_hours=ttl_hours)
        
        # 1. Buscar posts en ChromaDB que superen el TTL
        # Usamos el filtro where en metadatos. Asumimos que guardamos 'scraped_at_ts'
        expired_results = chroma_collection.get(
            where={"scraped_at_ts": {"$lt": cutoff_ts}},
            include=["metadatas"]
        )
        
        ids_to_delete = expired_results.get("ids", [])
        if not ids_to_delete:
            logger.info("no_expired_posts_found")
            return 0
            
        logger.info("expired_posts_found", count=len(ids_to_delete))
        
        # 2. Eliminar de MinIO
        # Cada post en ChromaDB tiene en su metadata la 'minio_key'
        for metadata in expired_results.get("metadatas", []):
            minio_key = metadata.get("minio_key")
            if minio_key:
                minio_client.delete_post(minio_key)
        
        # 3. Eliminar de ChromaDB
        chroma_collection.delete(ids=ids_to_delete)
        
        logger.info("ttl_purge_complete", deleted_count=len(ids_to_delete))
        return len(ids_to_delete)
        
    except Exception as e:
        logger.error("ttl_purge_failed", error=str(e))
        return 0
