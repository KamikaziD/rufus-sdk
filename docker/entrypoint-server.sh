#!/bin/bash
set -e

echo "==================================="
echo "  Rufus Server Initialization"
echo "==================================="

# Wait for database to be ready
echo "Waiting for database..."
sleep 5

# Run Alembic migrations
echo "Running database migrations with Alembic..."
cd /app/src/ruvon
alembic upgrade head

if [ $? -eq 0 ]; then
    echo "✓ Database migrations completed successfully"
else
    echo "✗ Database migrations failed!"
    exit 1
fi

cd /app

# Start the server
echo "Starting Rufus server..."
exec uvicorn ruvon_server.main:app --host 0.0.0.0 --port 8000
