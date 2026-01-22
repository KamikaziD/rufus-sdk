import redis.asyncio as redis
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RedisClient:
    def __init__(self, host='localhost', port=6379, db=0):
        try:
            self.client = redis.Redis(host=host, port=port, db=db, decode_responses=True, health_check_interval=30)
            logger.info("Successfully connected to Redis.")
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Could not connect to Redis: {e}")
            self.client = None

    async def save_workflow(self, workflow_id: str, workflow_data: dict):
        if self.client:
            try:
                await self.client.set(f"workflow:{workflow_id}", json.dumps(workflow_data))
                logger.info(f"Workflow {workflow_id} saved to Redis.")
            except Exception as e:
                logger.error(f"Error saving workflow {workflow_id} to Redis: {e}")

    async def load_workflow(self, workflow_id: str):
        if self.client:
            try:
                data = await self.client.get(f"workflow:{workflow_id}")
                if data:
                    logger.info(f"Workflow {workflow_id} loaded from Redis.")
                    return json.loads(data)
                else:
                    logger.warning(f"Workflow {workflow_id} not found in Redis.")
                    return None
            except Exception as e:
                logger.error(f"Error loading workflow {workflow_id} from Redis: {e}")
                return None
        return None

    async def publish_event(self, channel: str, message: dict):
        if self.client:
            try:
                await self.client.publish(channel, json.dumps(message))
                logger.info(f"Published event to channel {channel}: {message}")
            except Exception as e:
                logger.error(f"Error publishing event to channel {channel}: {e}")

redis_client = RedisClient()
