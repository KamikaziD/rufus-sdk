#!/bin/bash
# Quick start script for Rufus distributed Celery deployment

set -e

echo "=========================================="
echo "  Rufus Distributed Celery Quick Start"
echo "=========================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    exit 1
fi

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "✅ Created .env - please review and customize if needed"
fi

# Build images
echo ""
echo "🔨 Building Docker images..."
docker-compose -f docker-compose.production.yml build

# Start infrastructure
echo ""
echo "🚀 Starting PostgreSQL and Redis..."
docker-compose -f docker-compose.production.yml up -d postgres redis

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL..."
sleep 5
until docker-compose -f docker-compose.production.yml exec -T postgres pg_isready -U rufus > /dev/null 2>&1; do
    echo "   Still waiting for PostgreSQL..."
    sleep 2
done
echo "✅ PostgreSQL is ready"

# Create database if it doesn't exist
echo "🗄️  Creating database if needed..."
docker-compose -f docker-compose.production.yml exec -T postgres psql -U rufus -d postgres -tc \
    "SELECT 1 FROM pg_database WHERE datname = 'rufus_production'" | grep -q 1 || \
    docker-compose -f docker-compose.production.yml exec -T postgres createdb -U rufus rufus_production
echo "✅ Database ready"

# Wait for Redis to be ready
echo "⏳ Waiting for Redis..."
until docker-compose -f docker-compose.production.yml exec -T redis redis-cli ping > /dev/null 2>&1; do
    echo "   Still waiting for Redis..."
    sleep 2
done
echo "✅ Redis is ready"

# Apply database migrations
echo ""
echo "📦 Applying database migrations..."
docker-compose -f docker-compose.production.yml run --rm rufus-server \
    sh -c "cd src/rufus && alembic upgrade head"
echo "✅ Migrations applied"

# Start workers
WORKER_COUNT=${1:-3}
echo ""
echo "🐝 Starting $WORKER_COUNT Celery workers..."
docker-compose -f docker-compose.production.yml up -d --scale celery-worker=$WORKER_COUNT

# Start monitoring and API
echo ""
echo "📊 Starting Flower monitoring and API server..."
docker-compose -f docker-compose.production.yml up -d flower rufus-server

# Wait a bit for workers to register
echo ""
echo "⏳ Waiting for workers to register..."
sleep 5

# Show status
echo ""
echo "=========================================="
echo "  Deployment Status"
echo "=========================================="
docker-compose -f docker-compose.production.yml ps

echo ""
echo "=========================================="
echo "  🎉 Deployment Complete!"
echo "=========================================="
echo ""
echo "📊 Flower Dashboard: http://localhost:5555"
echo "🌐 API Server: http://localhost:8000"
echo ""
echo "Useful commands:"
echo "  - Scale workers: docker-compose -f docker-compose.production.yml up -d --scale celery-worker=10"
echo "  - View logs: docker-compose -f docker-compose.production.yml logs -f celery-worker"
echo "  - Stop all: docker-compose -f docker-compose.production.yml down"
echo ""
