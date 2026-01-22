from fastapi import UploadFile, File
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class AgentType(str, Enum):
    MASTER = "master"
    OCR = "ocr"
    INFO = "info"
    RAG = "rag"

class ExecutionMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"

class LogEntry(BaseModel):
    agent: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.now)
    is_error: bool = False

class ReasoningStep(BaseModel):
    step: str
    thought: str
    timestamp: datetime = Field(default_factory=datetime.now)

class PlanStep(BaseModel):
    id: int
    agent: str
    action: str
    depends_on: List[int] = []
    reasoning: str

class ExecutionPlan(BaseModel):
    steps: List[PlanStep]
    agents: List[str]
    execution_mode: ExecutionMode
    estimated_time: int

class AgentResult(BaseModel):
    agent_type: AgentType
    result: Dict[str, Any]
    execution_time: float
    model_used: str

class AgentRequest(BaseModel):
    query: str
    context: Optional[str] = None
    collections: Optional[List[str]] = None
    urls: Optional[List[str]] = None
    files: Optional[List[UploadFile]] = None

    class Config:
        arbitrary_types_allowed = True
