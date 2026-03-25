import json
import structlog
from pymongo import MongoClient, UpdateOne
from datetime import datetime, timezone

logger = structlog.get_logger()

class MongoDBClient:
    def __init__(self, uri: str, db_name: str, collection_name: str):
        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]
        
    def ensure_indices(self, vector_index_name: str):
        """Creates necessary indices for the collection."""
        # Standard index for URI (uniqueness)
        self.collection.create_index("uri", unique=True)
        # Standard index for created_at (for sorting/history)
        self.collection.create_index("created_at")
        
        # Note: Vector indices in Atlas Local are created via API/Shell as they are 'search' indices.
        # But we can define the metadata here if needed.
        logger.info("mongodb_indices_ensured", collection=self.collection.name)

    def upload_post(self, post: dict, embedding: list[float] = None, misogyny_score: float = 0.0) -> str:
        """Upserts a post into MongoDB, optionally with an embedding and score."""
        try:
            document = {
                **post,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "misogyny_score": misogyny_score
            }
            if embedding:
                document["embedding"] = embedding
                
            # Use URI as the unique identifier
            self.collection.update_one(
                {"uri": post["uri"]},
                {"$set": document},
                upsert=True
            )
            return post["uri"]
        except Exception as e:
            logger.error("mongodb_upload_failed", uri=post.get("uri"), error=str(e))
            raise

    def vector_search(self, embedding: list[float], limit: int = 5, index_name: str = "vector_index"):
        """Performs a vector search. Fallback to manual similarity since standard Mongo lacks Vector Index."""
        # Note: In a production environment with many docs, you'd use a real vector DB or Atlas.
        # Here we fetch the latest 500 posts and rank them.
        cursor = self.collection.find({"embedding": {"$exists": True}}).sort("created_at", -1).limit(200)
        
        results = []
        import numpy as np
        
        query_vec = np.array(embedding)
        
        for doc in cursor:
            doc_vec = np.array(doc["embedding"])
            # Cosine similarity
            score = np.dot(query_vec, doc_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(doc_vec))
            doc["$vectorSearchScore"] = float(score)
            results.append(doc)
            
        # Sort by score descending
        results.sort(key=lambda x: x["$vectorSearchScore"], reverse=True)
        return results[:limit]

    def get_stats(self):
        """Returns basic statistics from the collection."""
        return {
            "count": self.collection.count_documents({}),
            "latest": list(self.collection.find().sort("created_at", -1).limit(1))
        }
