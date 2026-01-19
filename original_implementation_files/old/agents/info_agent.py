from old.agents.base_agent import BaseAgent
from old.models.agent import AgentType
from old.services.ollama import ollama_service
from old.services.redis_service import redis_service
from old.config import settings
from typing import Dict, Any, Optional, Callable, Awaitable

class InfoAgent(BaseAgent):
    def __init__(self, model: str, system_prompt: str, client_id: Optional[str] = None, is_cancelled: Optional[Callable[[], Awaitable[bool]]] = None):
        super().__init__(AgentType.INFO, model, client_id=client_id, is_cancelled=is_cancelled)
        self.system_prompt = system_prompt
    
    async def execute(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute information gathering"""
        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")
        
        # Check cache
        cache_key = f"info:{query}"
        if context and "text" in context:
            cache_key += f":{hash(context['text'])}"

        cached = await redis_service.get(cache_key)
        if cached:
            return cached
        
        prompt = f"""Research and provide comprehensive information about: "{query}"

Provide:
1. A summary of the topic
2. Key insights and important points
3. Relevant context and background

Format your response clearly and concisely."""

        if context and "text" in context:
            prompt += f"\n\nDOCUMENT CONTEXT:\n{context['text']}"
        
        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")

        result, duration = await self._measure_execution(
            ollama_service.generate,
            prompt,
            self.system_prompt,
            self.model
        )
        
        response = {
            "query": query,
            "full_response": result,
            "result_count": 3,
            "model": self.model,
            "execution_time": duration
        }
        
        # Cache result
        await redis_service.set(cache_key, response, settings.CACHE_TTL_MEDIUM)
        
        return response
