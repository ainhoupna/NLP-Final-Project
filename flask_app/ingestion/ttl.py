import structlog
from datetime import datetime, timezone, timedelta

logger = structlog.get_logger()

def purge_expired_posts_mongo(mongo_client, ttl_hours: int) -> int:
    """Elimina los posts cuya antigüedad sea superior al TTL."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        
        # En MongoDB podemos borrar directamente los documentos antiguos
        # Asumiendo que guardamos 'scraped_at' como ISO string, o mejor aún, como objeto Date.
        # Si es ISO string:
        cutoff_iso = cutoff.isoformat()
        
        result = mongo_client.collection.delete_many({
            "scraped_at": {"$lt": cutoff_iso}
        })
        
        count = result.deleted_count
        if count > 0:
            logger.info("posts_purged_mongo", count=count, cutoff=cutoff_iso)
        return count
    except Exception as e:
        logger.error("purge_failed_mongo", error=str(e))
        return 0
