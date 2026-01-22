from old.agents.base_agent import BaseAgent
from old.models.agent import AgentType
from old.services.ollama import ollama_service
from old.services.file_service import file_service
from typing import Dict, Any, Optional, Callable, Awaitable


class OCRAgent(BaseAgent):
    def __init__(self, model: str, system_prompt: str, client_id: Optional[str] = None, is_cancelled: Optional[Callable[[], Awaitable[bool]]] = None):
        super().__init__(AgentType.OCR, model, client_id=client_id, is_cancelled=is_cancelled)
        self.system_prompt = system_prompt

    async def execute(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute OCR analysis on text and images from context and URLs."""
        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")

        context = context or {}
        all_text_parts = [context.get("text", "")]
        all_image_parts = context.get("images", [])

        urls = context.get("urls", [])
        if urls:
            await self.report_activity(f"Fetching content from {len(urls)} URLs...")
            try:
                url_files = await file_service.get_files_from_urls(urls)
                processed_url_files = [
                    file_service.read_file_content(f) for f in url_files]
                
                for item in processed_url_files:
                    if self.is_cancelled and await self.is_cancelled():
                        raise Exception("Task revoked")
                    if item["type"] == "text":
                        all_text_parts.append(item["content"])
                    elif item["type"] == "image":
                        all_image_parts.append(item["content"])
                await self.report_activity("URL content fetched successfully.")
            except Exception as e:
                await self.report_activity(
                    f"Error fetching URL content: {e}", is_error=True)

        text_to_analyze = "\n\n".join(
            part for part in all_text_parts if part and part.strip())

        if not text_to_analyze.strip() and not all_image_parts:
            text_to_analyze = query
            await self.report_activity(
                "No text or image content found, using query as text to analyze.")

        prompt = f"""Analyze the following text and images based on the user's query: "{query}".
Document Text: "{text_to_analyze}"

Provide your analysis in the following format:
Document Type: [type]
Confidence: [0-1]
Key Information: [bullet points of extracted data]"""

        if self.is_cancelled and await self.is_cancelled():
            raise Exception("Task revoked")

        result, duration = await self._measure_execution(
            ollama_service.generate,
            prompt=prompt,
            system_prompt=self.system_prompt,
            model=self.model,
            images=all_image_parts
        )

        return {
            "text": text_to_analyze,
            "analysis": result,
            "confidence": 0.95,
            "detected_type": self._detect_document_type(text_to_analyze),
            "model": self.model,
            "execution_time": duration
        }

    def _detect_document_type(self, text: str) -> str:
        """Simple document type detection"""
        text_lower = text.lower()
        if "invoice" in text_lower:
            return "invoice"
        elif "receipt" in text_lower:
            return "receipt"
        elif "contract" in text_lower:
            return "contract"
        elif "report" in text_lower:
            return "report"
        return "general document"
