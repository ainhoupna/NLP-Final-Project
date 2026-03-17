"""Cliente de MinIO para almacenamiento de posts."""

from __future__ import annotations
import json
import io
import structlog
from minio import Minio
from minio.error import S3Error

logger = structlog.get_logger()

class MinIOClient:
    """Wrapper sobre el cliente de MinIO para operaciones con posts."""

    def __init__(self, url: str, access_key: str, secret_key: str, bucket: str) -> None:
        """Inicializa el cliente de MinIO."""
        self.client = Minio(
            url,
            access_key=access_key,
            secret_key=secret_key,
            secure=False # Usamos HTTP para local
        )
        self.bucket = bucket

    def ensure_bucket(self) -> None:
        """Crea el bucket si no existe."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info("minio_bucket_created", bucket=self.bucket)
            else:
                logger.info("minio_bucket_exists", bucket=self.bucket)
        except S3Error as e:
            logger.error("minio_ensure_bucket_failed", error=str(e))

    def upload_post(self, post: dict) -> str:
        """Serializa el post a JSON y lo sube a MinIO."""
        try:
            # Generar una key única basada en el CID o URI
            # Bluesky URIs suelen ser at://did:plc:.../app.bsky.feed.post/...
            # Reemplazamos caracteres problemáticos para S3 keys
            object_name = post["uri"].replace("at://", "").replace("/", "_") + ".json"
            
            data = json.dumps(post).encode('utf-8')
            data_stream = io.BytesIO(data)
            
            self.client.put_object(
                self.bucket,
                object_name,
                data_stream,
                length=len(data),
                content_type='application/json'
            )
            return object_name
        except Exception as e:
            logger.error("minio_upload_failed", uri=post.get("uri"), error=str(e))
            raise

    def delete_post(self, object_name: str) -> None:
        """Elimina un post de MinIO."""
        try:
            self.client.remove_object(self.bucket, object_name)
        except S3Error as e:
            logger.error("minio_delete_failed", key=object_name, error=str(e))

    def list_posts(self) -> list:
        """Lista los objetos del bucket."""
        try:
            objects = self.client.list_objects(self.bucket, recursive=True)
            return list(objects)
        except S3Error as e:
            logger.error("minio_list_failed", error=str(e))
            return []
