"""Gestión del TTL (Time-To-Live) de posts.

Purga automáticamente los posts cuyo ``scraped_at_ts`` supere
el umbral configurado, eliminándolos tanto de ChromaDB como de MinIO.
"""

from __future__ import annotations

from flask_app.ingestion.minio_client import MinIOClient


def purge_expired_posts(
    chroma_collection,
    minio_client: MinIOClient,
    ttl_hours: int = 24,
) -> int:
    """Elimina posts con ``scraped_at_ts`` anterior al umbral de TTL.

    Borra los posts expirados tanto de la colección de ChromaDB
    como del bucket de MinIO.

    Args:
        chroma_collection: Colección de ChromaDB donde están indexados los posts.
        minio_client: Cliente de MinIO para eliminar los objetos JSON.
        ttl_hours: Umbral de antigüedad en horas (por defecto 24).

    Returns:
        Número de posts eliminados.
    """
    raise NotImplementedError
