# Simple Dockerfile for Confucius API
FROM python:3.11-slim

# Avoid buffering output
ENV PYTHONUNBUFFERED=1

# Create app directory
WORKDIR /app

# Install system deps required by some packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    curl \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt /app/requirements.txt

# Install Python deps
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r /app/requirements.txt

# Copy project
COPY . /app

# Ensure src is importable (main.py already adjusts sys.path, but keep PYTHONPATH)
ENV PYTHONPATH=/app/src:${PYTHONPATH}

EXPOSE 8000

# Default command: run the FastAPI app
CMD ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port 8000 --reload"]