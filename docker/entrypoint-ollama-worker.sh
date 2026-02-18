#!/bin/bash
set -e

echo "================================================"
echo "Rufus GPU Worker with Ollama"
echo "================================================"

# Start Ollama server in background
echo "Starting Ollama server..."
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to be ready
echo "Waiting for Ollama server to start..."
for i in {1..30}; do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "✅ Ollama server is ready"
        break
    fi
    echo "Waiting... ($i/30)"
    sleep 2
done

# Pull default models if specified
if [ ! -z "$OLLAMA_MODELS" ]; then
    echo "Pulling Ollama models: $OLLAMA_MODELS"
    IFS=',' read -ra MODELS <<< "$OLLAMA_MODELS"
    for model in "${MODELS[@]}"; do
        echo "Pulling model: $model"
        ollama pull "$model" || echo "⚠️  Failed to pull $model (will retry on first use)"
    done
fi

# Start Celery worker
echo "Starting Celery worker..."
exec celery -A rufus.celery_app worker \
    --loglevel=${WORKER_LOG_LEVEL} \
    --concurrency=${WORKER_CONCURRENCY} \
    --pool=${WORKER_POOL} \
    -Q gpu-inference,llm-inference \
    -n ${WORKER_ID}@%h
