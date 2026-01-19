import redis
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def redis_listener(host='localhost', port=6379, db=0):
    try:
        r = redis.Redis(host=host, port=port, db=db)
        p = r.pubsub()
        p.subscribe('workflow_events')
        logger.info("Subscribed to 'workflow_events' channel. Waiting for messages...")

        for message in p.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    logger.info(f"Received event: {json.dumps(data, indent=2)}")
                except json.JSONDecodeError:
                    logger.warning(f"Received non-JSON message: {message['data']}")
    except redis.exceptions.ConnectionError as e:
        logger.error(f"Could not connect to Redis: {e}")
    except Exception as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    redis_listener()
