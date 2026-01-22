from fastapi import APIRouter, HTTPException, File, UploadFile, Form
from old.services.redis_service import redis_service
from typing import List, Optional
import json
import logging
from old.tasks.tasks import execute_master_agent_task, celery_app

logger = logging.getLogger(__name__)

router = APIRouter()

# Default system prompts
DEFAULT_PROMPTS = {
    "master": "You are a master orchestration agent. Analyze requests, create efficient execution plans, and coordinate specialized agents to achieve user goals.",
    "ocr": "You are an OCR analysis agent. Extract and structure information from documents accurately.",
    "info": "You are an information gathering agent. Synthesize web search results into clear, accurate summaries.",
    "rag": "You are a RAG (Retrieval-Augmented Generation) agent. Combine vector search results and knowledge base information to provide accurate, contextual responses."
}


@router.post("/execute")
async def execute_agents(
    client_id: str = Form(...),
    query: str = Form(...),
    context: Optional[str] = Form(None),
    collections: List[str] = Form([]),
    urls: List[str] = Form([]),
    files: List[UploadFile] = File([]),
):
    """Execute the multi-agent system asynchronously via Celery"""
    try:
        # Prepare files data for Celery task
        files_data = []
        for file in files:
            content = await file.read()
            files_data.append({"filename": file.filename, "content": content})

        # Enqueue the task
        task = execute_master_agent_task.delay(
            query=query,
            context_str=context,
            collections_json=json.dumps(collections),
            urls_json=json.dumps(urls),
            files_data=files_data,
            client_id=client_id,
        )

        return {"message": "Task accepted", "task_id": task.id, "client_id": client_id}

    except Exception as e:
        logger.error(f"Error in execute_agents endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a running task"""
    try:
        await redis_service.set(f"task:{task_id}:cancelled", "true", ttl=3600)
        celery_app.control.revoke(task_id, terminate=True)
        return {"message": "Task cancellation requested"}
    except Exception as e:
        logger.error(f"Error cancelling task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
