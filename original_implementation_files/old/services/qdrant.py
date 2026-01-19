from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from typing import List, Dict, Any, Optional
from app.config import settings
import uuid

class QdrantService:
    def __init__(self):
        # Use AsyncQdrantClient for async operations
        self.client: AsyncQdrantClient = AsyncQdrantClient(url=settings.QDRANT_URL)
    
    async def create_collection(self, collection_name: str, vector_size: int = 768):
        """Create a new collection"""
        await self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
        )
    
    async def list_collections(self) -> List[Dict[str, Any]]:
        """List all collections"""
        collections = await self.client.get_collections()
        return [{"name": c.name} for c in collections.collections]
    
    async def delete_collection(self, collection_name: str):
        """Delete a collection"""
        await self.client.delete_collection(collection_name=collection_name)
    
    async def add_point(
        self,
        collection_name: str,
        vector: List[float],
        payload: Dict[str, Any]
    ) -> str:
        """Add a point to collection"""
        point_id = str(uuid.uuid4())
        
        await self.client.upsert(
            collection_name=collection_name,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
            wait=True # Ensure the operation is completed
        )
        
        return point_id
    
    async def search(
        self,
        collection_name: str,
        query_vector: List[float],
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar vectors"""
        results = await self.client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=limit
        )
        
        return [
            {
                "id": str(result.id),
                "score": result.score,
                "payload": result.payload
            }
            for result in results
        ]
    
    async def check_connection(self) -> bool:
        """Check if Qdrant is available"""
        try:
            await self.client.get_collections()
            return True
        except:
            return False

qdrant_service = QdrantService()
