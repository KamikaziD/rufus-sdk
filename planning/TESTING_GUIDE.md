# Ruvon Celery Testing Guide

Complete guide for testing Ruvon's Celery-based distributed execution.

## Quick Start

**1. Start test infrastructure:**
```bash
cd tests/integration
docker-compose up -d
```

**2. Apply database migrations:**
```bash
cd ../../src/ruvon
export DATABASE_URL="postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_test"
alembic upgrade head
```

**3. Start Celery worker:**
```bash
export DATABASE_URL="postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_test"
export CELERY_BROKER_URL="redis://localhost:6380/0"
export CELERY_RESULT_BACKEND="redis://localhost:6380/0"

celery -A ruvon.celery_app worker --loglevel=info --concurrency=4
```

**4. Run tests (in another terminal):**
```bash
export DATABASE_URL="postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_test"
export CELERY_BROKER_URL="redis://localhost:6380/0"
export CELERY_RESULT_BACKEND="redis://localhost:6380/0"

pytest tests/integration/test_celery_execution.py -v -s
```

**5. Cleanup:**
```bash
cd tests/integration
docker-compose down -v
```

See tests/integration/README.md for comprehensive documentation.
