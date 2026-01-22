import httpx
from typing import List, Optional, Dict, Any
from old.config import settings


class OllamaService:
    def __init__(self):
        self.base_url = settings.OLLAMA_URL

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        model: str,
        stream: bool = False,
        images: Optional[List[str]] = None
    ) -> str:
        """Generate completion from Ollama, with optional image support for vision models."""
        async with httpx.AsyncClient(timeout=settings.OLLAMA_GENERATE_TIMEOUT) as client:
            payload = {
                "model": model,
                "prompt": prompt,
                "system": system_prompt,
                "stream": stream,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9
                }
            }
            if images:
                payload["images"] = images

            response = await client.post(
                f"{self.base_url}/api/generate",
                json=payload
            )

            response.raise_for_status()
            data = response.json()
            return data.get("response", "")

    async def generate_embedding(self, text: str, model: str) -> List[float]:
        """Generate embedding from Ollama"""
        async with httpx.AsyncClient(timeout=settings.OLLAMA_EMBEDDING_TIMEOUT) as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": model,
                    "prompt": text
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("embedding", [])

    async def list_models(self) -> List[Dict[str, Any]]:
        """List available models"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return data.get("models", [])

    async def check_connection(self) -> bool:
        """Check if Ollama is available"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except Exception:
            return False


ollama_service = OllamaService()
