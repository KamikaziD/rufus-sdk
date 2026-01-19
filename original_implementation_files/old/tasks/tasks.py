from celery_app import celery_app
from old.agents import MasterAgent
from old.services.redis_service import redis_service
from old.services.file_service import file_service
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging
import asyncio

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=3, default_retry_delay=60) # Modified decorator
def execute_master_agent_task(
    self,
    query: str,
    context_str: Optional[str],
    collections_json: str,
    urls_json: str,
    files_data: List[Dict[str, Any]],
    client_id: str
):
    async def _is_cancelled():
        return await redis_service.get(f"task:{self.request.id}:cancelled")

    async def main():
        try:
            # Deserialize inputs
            collections = json.loads(collections_json)
            urls = json.loads(urls_json)
            context = json.loads(context_str) if context_str else {}

            # Get agent models from Redis or use defaults
            agent_models_data = await redis_service.get("agent_models")
            agent_models = agent_models_data or {
                "master": "qwen3-vl:4b",
                "ocr": "qwen3-vl:4b",
                "info": "qwen3-vl:4b",
                "rag": "qwen3-vl:4b",
                "embedding": "qwen3-embedding:8b"
            }

            # Get system prompts from Redis or use defaults
            system_prompts_data = await redis_service.get("system_prompts")
            if system_prompts_data:
                system_prompts = {
                    key: prompt["current"]
                    for key, prompt in system_prompts_data.items()
                }
            else:
                system_prompts = {
                    "master": "You are a master orchestration agent. Analyze requests, create efficient execution plans, and coordinate specialized agents to achieve user goals.",
                    "ocr": "You are an OCR analysis agent. Extract and structure information from documents accurately.",
                    "info": "You are an information gathering agent. Synthesize web search results into clear, accurate summaries.",
                    "rag": "You are a RAG (Retrieval-Augmented Generation) agent. Combine vector search results and knowledge base information to provide accurate, contextual responses."
                }

            master = MasterAgent(
                agent_models, system_prompts, client_id=client_id, is_cancelled=_is_cancelled
            )

            # Process uploaded files
            processed_files_for_service = []
            for fd in files_data:
                processed_files_for_service.append(
                    {"filename": fd["filename"], "content": fd["content"]})

            text_parts = []
            image_parts = []
            if processed_files_for_service:
                logger.info(
                    f"Task {self.request.id}: Processing {len(processed_files_for_service)} uploaded files.")
                file_contents = [file_service.read_file_content(f)
                                 for f in processed_files_for_service]
                for item in file_contents:
                    if item["type"] == "text":
                        text_parts.append(item["content"])
                    elif item["type"] == "image":
                        image_parts.append(item["content"])
                logger.info(
                    f"Task {self.request.id}: Processed {len(text_parts)} text files and {len(image_parts)} image files.")

            # Combine context
            final_context = context.get("text", "")
            if text_parts:
                final_context += "\n\n" + "\n\n".join(text_parts)

            # Execute
            exec_context = {}
            if collections:
                exec_context["collections"] = collections
            if final_context:
                exec_context["text"] = final_context
            if urls:
                exec_context["urls"] = urls
            if image_parts:
                exec_context["images"] = image_parts

            result = await master.execute(query, exec_context)

            # Save to history
            session_id = str(uuid.uuid4())
            session = {
                "id": session_id,
                "input": query,
                "context": final_context,
                "result": result["final_result"],
                "plan": result["plan"],
                "status": result["status"],
                "duration": result["duration"],
                "timestamp": datetime.now().isoformat(),
                "model": agent_models["master"]
            }
            await redis_service.set(f"history:{session_id}", session, 2592000)

            # Publish event to client via Redis Pub/Sub
            await redis_service.publish(f"agent_results:{client_id}", json.dumps({
                "task_id": self.request.id,
                "status": "SUCCESS",
                "result": result
            }))

            # Publish final task completion event from the worker
            final_worker_message = {
                "type": "activity_update",
                "agent": "System",
                "message": "Task processing complete.",
                "is_error": False,
                "task_id": self.request.id,
                "event_id": str(uuid.uuid4())
            }
            await redis_service.publish(f"agent_activity:{client_id}", json.dumps(final_worker_message))

            return result

        except Exception as e:
            logger.error(
                f"Task {self.request.id}: Error during master agent execution: {e}", exc_info=True)
            if await _is_cancelled():
                logger.warning(f"Task {self.request.id} was revoked.")
                await redis_service.publish(f"agent_results:{client_id}", json.dumps({
                    "task_id": self.request.id,
                    "status": "REVOKED",
                }))
                # Re-raise the exception to mark the task as failed
                raise e
            else:
                    # This is a recoverable failure, so retry
                    await redis_service.publish(f"agent_results:{client_id}", json.dumps({
                        "task_id": self.request.id,
                        "status": "RETRY",
                        "error": str(e),
                        "retries": self.request.retries
                    }))
                    raise self.retry(exc=e)
    
    return asyncio.run(main())
