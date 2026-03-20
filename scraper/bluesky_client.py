from __future__ import annotations
from datetime import datetime, timezone
import structlog
from atproto import Client

logger = structlog.get_logger()

class BlueskyClient:
    """Cliente para interactuar con la API de Bluesky vía AT Protocol."""

    def __init__(self, handle: str, app_password: str) -> None:
        """Inicializa el cliente con credenciales de Bluesky."""
        self.handle = handle
        self.app_password = app_password
        self.client = Client()

    def login(self) -> None:
        """Autentica contra el servidor de Bluesky."""
        try:
            self.client.login(self.handle, self.app_password)
            logger.info("atproto_login_success", handle=self.handle)
        except Exception as e:
            logger.error("atproto_login_failed", error=str(e))
            raise

    def search_posts(self, query: str, limit: int = 50) -> list[dict]:
        """Busca posts por query y los devuelve normalizados."""
        try:
            # Documented at: https://atproto.blue/en/latest/atproto_client/models/index.html
            response = self.client.app.bsky.feed.search_posts(params={"q": query, "limit": limit})
            normalized_posts = [normalize_post(post) for post in response.posts]
            logger.info("atproto_search_success", query=query, count=len(normalized_posts))
            return normalized_posts
        except Exception as e:
            logger.error("atproto_search_failed", query=query, error=str(e))
            return []

    def search_posts_paginated(self, query: str, limit: int = 50, since: str | None = None, until: str | None = None, cursor: str | None = None, retries: int = 3) -> tuple[list[dict], str | None]:
        """Busca posts por query con paginación explícita temporal y manejo de rate limit."""
        import time
        for attempt in range(retries):
            try:
                # We use native since/until parameters provided by the search API
                params = {"q": query, "limit": limit}
                if since:
                    params["since"] = since
                if until:
                    params["until"] = until
                if cursor:
                    params["cursor"] = cursor
                    
                response = self.client.app.bsky.feed.search_posts(params=params)
                normalized_posts = [normalize_post(post) for post in response.posts]
                logger.info("atproto_search_paginated_success", query=query, count=len(normalized_posts), has_cursor=bool(response.cursor))
                return normalized_posts, response.cursor
                
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "RateLimitExceeded" in err_msg:
                    wait_time = 300 # Wait 5 minutes by default for rate limit
                    logger.warning("atproto_rate_limit_exceeded", query=query, wait_seconds=wait_time, attempt=attempt+1)
                    time.sleep(wait_time)
                    continue
                
                logger.error("atproto_search_paginated_failed", query=query, error=err_msg)
                return [], None
        
        return [], None

def normalize_post(post_view) -> dict:
    """Convierte un objeto de la API de atproto al formato canónico del proyecto."""
    # post_view es típicamente un objeto de la clase app.bsky.feed.defs.PostView
    
    author = post_view.author
    record = post_view.record # El contenido real del post (Main)
    
    # Extraer imágenes si existen
    images = []
    if hasattr(record, 'embed') and record.embed and hasattr(record.embed, 'images'):
        images = [img.alt for img in record.embed.images if hasattr(img, 'alt')]

    return {
        "uri": post_view.uri,
        "cid": post_view.cid,
        "author_did": author.did,
        "author_handle": author.handle,
        "text": record.text if hasattr(record, 'text') else "",
        "created_at": record.created_at if hasattr(record, 'created_at') else None,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "images": images,
        "langs": list(record.langs) if hasattr(record, 'langs') and record.langs else [],
        "labels": [l.val for l in post_view.labels] if hasattr(post_view, 'labels') and post_view.labels else [],
        "like_count": post_view.like_count or 0,
        "repost_count": post_view.repost_count or 0,
    }
