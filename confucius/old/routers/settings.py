from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from old.services.redis_service import redis_service
from old.services.ollama import ollama_service
from old.services.qdrant import qdrant_service
from datetime import datetime

router = APIRouter()


class AgentModelsUpdate(BaseModel):
    master: str
    ocr: str
    info: str
    rag: str
    embedding: str


class SystemPromptUpdate(BaseModel):
    agent: str
    prompt: str


class CollectionSelection(BaseModel):
    collections: List[str]


@router.get("/models")
async def get_available_models():
    """Get available Ollama models"""
    try:
        models = await ollama_service.list_models()
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agent-models")
async def get_agent_models():
    """Get current agent model configuration"""
    models = await redis_service.get("agent_models")
    if not models:
        models = {
            "master": "qwen3-vl:4b",
            "ocr": "qwen3-vl:4b",
            "info": "qwen3-vl:4b",
            "rag": "qwen3-vl:4b",
            "embedding": "qwen3-embedding:4b"
        }
    return models


@router.post("/agent-models")
async def update_agent_models(models: AgentModelsUpdate):
    """Update agent model configuration"""
    await redis_service.set("agent_models", models.dict())
    return {"success": True}


@router.get("/system-prompts")
async def get_system_prompts():
    """Get system prompts"""
    prompts = await redis_service.get("system_prompts")
    if not prompts:
        from old.routers.agents import DEFAULT_PROMPTS
        prompts = {
            key: {
                "current": value,
                "versions": [],
                "name": f"{key.upper()} Agent System Prompt"
            }
            for key, value in DEFAULT_PROMPTS.items()
        }
    return prompts


@router.post("/system-prompts")
async def update_system_prompt(update: SystemPromptUpdate):
    """Update system prompt"""
    prompts = await get_system_prompts()

    if update.agent not in prompts:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Save current as version
    version = {
        "prompt": prompts[update.agent]["current"],
        "timestamp": datetime.now().isoformat(),
        "model": "unknown"
    }

    prompts[update.agent]["versions"].insert(0, version)
    # Keep last 10
    prompts[update.agent]["versions"] = prompts[update.agent]["versions"][:10]
    prompts[update.agent]["current"] = update.prompt

    await redis_service.set("system_prompts", prompts)
    return {"success": True}


@router.get("/connections")
async def check_connections():
    """Check all service connections"""
    return {
        "ollama": await ollama_service.check_connection(),
        "qdrant": await qdrant_service.check_connection(),
        "redis": await redis_service.ping()
    }


@router.get("/selected-collections")
async def get_selected_collections():
    """Get selected collections for RAG"""
    collections = await redis_service.get("selected_collections")
    return {"collections": collections or ["documents"]}


@router.post("/selected-collections")
async def update_selected_collections(selection: CollectionSelection):
    """Update selected collections"""
    await redis_service.set("selected_collections", selection.collections)
    return {"success": True}
