from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

class ConversationSession(BaseModel):
    id: str
    input: str
    result: str
    logs: List[Dict[str, Any]]
    reasoning: List[Dict[str, Any]]
    plan: Optional[Dict[str, Any]]
    status: str  # success, failed
    duration: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    model: Optional[str] = None
    services: Optional[Dict[str, bool]] = None
