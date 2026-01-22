import redis
import json
from typing import Optional, Any, List
from old.config import settings

class RedisService:
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
    
    async def connect(self):
        """Connect to Redis (async)"""
        self.redis = redis.asyncio.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            decode_responses=True
        )
        # Ensure connection is established
        await self.redis.ping()
    
    async def disconnect(self):
        """Disconnect from Redis (async)"""
        if self.redis:
            await self.redis.close()

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache (async)"""
        if not self.redis:
            await self.connect() # Auto-connect if not connected
        
        value = await self.redis.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache (async)"""
        if not self.redis:
            await self.connect() # Auto-connect if not connected
        
        serialized = json.dumps(value) if not isinstance(value, str) else value
        
        if ttl:
            await self.redis.setex(key, ttl, serialized)
        else:
            await self.redis.set(key, serialized)
        
        return True
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache (async)"""
        if not self.redis:
            return False
        
        result = await self.redis.delete(key)
        return result > 0
    
    async def keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching pattern (async)"""
        if not self.redis:
            return []
        
        return await self.redis.keys(pattern)
    
    async def publish(self, channel: str, message: Any) -> int:
        """Publish message to channel (async)"""
        if not self.redis:
            await self.connect() # Auto-connect if not connected
        
        serialized = json.dumps(message) if not isinstance(message, str) else message
        return await self.redis.publish(channel, serialized)
    
    async def ping(self) -> bool:
        """Check if Redis is connected (async)"""
        if not self.redis:
            return False
        
        try:
            return await self.redis.ping()
        except:
            return False

redis_service = RedisService()
