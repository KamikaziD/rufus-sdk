from old.agents.base_agent import BaseAgent
from old.models.agent import AgentType
from old.services.ollama import ollama_service
from old.services.qdrant import qdrant_service
from old.services.redis_service import redis_service
from old.config import settings
from typing import Dict, Any, Optional, Callable, Awaitable

class RAGAgent(BaseAgent):
    def __init__(self, model: str, embedding_model: str, system_prompt: str, client_id: Optional[str] = None, is_cancelled: Optional[Callable[[], Awaitable[bool]]] = None):
        super().__init__(AgentType.RAG, model, client_id=client_id, is_cancelled=is_cancelled)
        self.embedding_model = embedding_model
        self.system_prompt = system_prompt
    
    async def execute(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute RAG with vector search"""
        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")
        
        collections = context.get("collections", [settings.QDRANT_DEFAULT_COLLECTION]) if context else [settings.QDRANT_DEFAULT_COLLECTION]
        
        # Check cache
        cache_key = f"rag:{query}:{':'.join(collections)}"
        cached = await redis_service.get(cache_key)
        if cached:
            return cached
        
        # Generate query embedding
        query_embedding = await ollama_service.generate_embedding(query, self.embedding_model)
        
        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")

        # Search across collections
        all_results = []
        for collection in collections:
            if self.is_cancelled and await self.is_cancelled():
                raise Exception("Task revoked")
            try:
                results = await qdrant_service.search(collection, query_embedding, limit=3)
                for r in results:
                    r["collection"] = collection
                all_results.extend(results)
            except Exception as e:
                await self.report_activity(f"Failed to search collection {collection}: {e}", is_error=True)
        
        # Sort by score
        all_results.sort(key=lambda x: x["score"], reverse=True)
        top_results = all_results[:5]
        
        # Build context
        vector_context = "\n\n".join([
            f"[Collection: {r['collection']}, Score: {r['score']:.3f}]\n{r['payload']}"
            for r in top_results
        ]) if top_results else "No similar documents found in vector database."
        
        prompt = f"""Using the following information sources, provide a comprehensive response:

Vector Search Results ({len(top_results)} documents from {len(collections)} collections):
{vector_context}

User Query: {query}
Additional Context: {context.get('text', '') if context else ''}

Provide a clear, helpful response that combines all available information."""
        
        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")
            
        result, duration = await self._measure_execution(
            ollama_service.generate,
            prompt,
            self.system_prompt,
            self.model
        )
        
        response = {
            "response": result,
            "vector_results": top_results,
            "vector_results_count": len(top_results),
            "collections_searched": collections,
            "model": self.model,
            "embedding_model": self.embedding_model,
            "execution_time": duration
        }
        
        # Cache result
        await redis_service.set(cache_key, response, settings.CACHE_TTL_MEDIUM)
        
        return response
