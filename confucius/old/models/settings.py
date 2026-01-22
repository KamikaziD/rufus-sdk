from pydantic import BaseModel
from typing import Dict, List, Optional, Any


class AgentModels(BaseModel):
    master: str = "qwen3-vl:4b"
    ocr: str = "qwen3-vl:4b"
    info: str = "qwen3-vl:4b"
    rag: str = "qwen3-vl:4b"
    embedding: str = "qwen3-embedding:8b"


class SystemPrompt(BaseModel):
    current: str
    versions: List[Dict[str, Any]] = []
    name: str


class SystemPrompts(BaseModel):
    master: SystemPrompt
    ocr: SystemPrompt
    info: SystemPrompt
    rag: SystemPrompt
