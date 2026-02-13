#!/bin/bash
# Start Celery worker for examples

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | xargs)
fi

# Set defaults if not in .env
export DATABASE_URL=${DATABASE_URL:-"postgresql://rufus:rufus_secret_2024@localhost:5432/rufus_example"}
export CELERY_BROKER_URL=${CELERY_BROKER_URL:-"redis://localhost:6379/0"}
export CELERY_RESULT_BACKEND=${CELERY_RESULT_BACKEND:-"redis://localhost:6379/0"}

# Add current directory to PYTHONPATH for task imports
export PYTHONPATH="$(pwd):$PYTHONPATH"

echo "=================================================="
echo "Starting Celery Worker for Examples"
echo "=================================================="
echo "Database: $DATABASE_URL"
echo "Broker:   $CELERY_BROKER_URL"
echo "Backend:  $CELERY_RESULT_BACKEND"
echo "=================================================="
echo ""

# Start worker with 4 concurrent tasks
celery -A rufus.celery_app worker \
    --loglevel=info \
    --concurrency=4 \
    --task-events \
    --without-gossip \
    --without-mingle \
    --without-heartbeat
