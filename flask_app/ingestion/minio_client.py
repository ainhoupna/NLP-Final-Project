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
            secure=False
        )
        self.bucket = bucket

    def ensure_bucket(self) -> None:
        """Crea el bucket si no existe."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except S3Error as e:
            logger.error("minio_ensure_bucket_failed", error=str(e))

    def download_post(self, object_name: str) -> dict:
        """Descarga un post de MinIO por su key."""
        try:
            response = self.client.get_object(self.bucket, object_name)
            data = response.read()
            return json.loads(data.decode('utf-8'))
        except Exception as e:
            logger.error("minio_download_failed", key=object_name, error=str(e))
            return {}
        finally:
            if 'response' in locals():
                response.close()
                response.release_conn()

    def list_posts(self) -> list:
        """Lista los objetos del bucket."""
        try:
            return list(self.client.list_objects(self.bucket, recursive=True))
        except S3Error as e:
            logger.error("minio_list_failed", error=str(e))
            return []
