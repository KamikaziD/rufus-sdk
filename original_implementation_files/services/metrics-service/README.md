# Real-time Events & Metrics Service

This folder contains the setup for real-time monitoring and metrics.

## Architecture

1.  **Event Publisher (`src/confucius/events.py`):** Publishes events to Redis Pub/Sub (`workflow:events:{id}`) and increments Prometheus counters.
2.  **WebSockets (`src/confucius/routers.py`):** Subscribes to Redis Pub/Sub channels and forwards events to connected frontend clients.
3.  **Metrics Service (Node.js):** A simple Express server exposing `/metrics` for Prometheus scraping (if we were using Node.js for metrics, but we are actually using `prometheus_client` in Python).

## Note on Metrics

The `prometheus_client` in Python exposes metrics directly from the Python application process. 
If you are running `uvicorn`, you might need to enable a metrics endpoint in FastAPI or run a separate exporter.

In this setup, we have integrated `prometheus_client` into `events.py`. 
To expose these metrics, we should mount a `/metrics` endpoint in `main.py`.

## Running the UI

The UI is served at `http://localhost:8000/debug/`.
It connects via WebSocket to `ws://localhost:8000/api/v1/workflow/{id}/subscribe`.
