from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Multi-Agent AI System"
    VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Ollama
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_DEFAULT_MODEL: str = "qwen3-vl:4b"
    OLLAMA_EMBEDDING_MODEL: str = "qwen3-embeddding:8b"
    OLLAMA_GENERATE_TIMEOUT: int = 600
    OLLAMA_EMBEDDING_TIMEOUT: int = 120

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_DEFAULT_COLLECTION: str = "documents"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    # Celery
    CELERY_BROKER_URL: str = "amqp://guest:guest@localhost:5672//"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Search
    SEARCH_PROVIDER: str = "duckduckgo"
    SERPER_API_KEY: Optional[str] = None
    SERPAPI_KEY: Optional[str] = None

    # Cache TTL
    CACHE_TTL_SHORT: int = 300  # 5 minutes
    CACHE_TTL_MEDIUM: int = 1800  # 30 minutes
    CACHE_TTL_LONG: int = 86400  # 24 hours

    SECRET_KEY: str = "minioadmin"
    ACCESS_KEY: str = "minioadmin"
    BUCKET_NAME: str = "test"

    class Config:
        env_file = ".env.local"


settings = Settings()
