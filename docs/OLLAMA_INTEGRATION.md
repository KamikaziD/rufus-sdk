# Ollama Integration Guide for Rufus GPU Workers

**Run local LLMs** (Llama, Mistral, CodeLlama) on GPU-enabled Celery workers using Ollama.

## Why Ollama?

Ollama makes running local LLMs **extremely simple**:
- ✅ **One-command model installation**: `ollama pull llama2`
- ✅ **Automatic GPU detection**: Works with CUDA, ROCm, Metal
- ✅ **Model quantization**: 4-bit, 5-bit, 8-bit for faster inference
- ✅ **Simple API**: REST API + Python client
- ✅ **50+ models**: Llama, Mistral, CodeLlama, Gemma, Phi, etc.

vs **Manual PyTorch/Transformers**:
- ❌ Complex model loading code
- ❌ Manual GPU memory management
- ❌ Dependency hell (torch, transformers, accelerate, bitsandbytes)
- ❌ Large model files (70B Llama = 140GB download)

## Architecture

```
┌───────────────────────────────────────────────────────────┐
│  Rufus Workflow                                           │
│  ├─ Step: "Generate_Summary"                              │
│  │   type: ASYNC                                          │
│  │   function: ollama_llm.tasks.generate_text            │
│  │   queue: llm-inference  ← Routes to Ollama workers    │
│  └─ ...                                                    │
└───────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│  Celery Task Queue (Redis)                                │
│  ├─ llm-inference queue                                   │
│  └─ gpu-inference queue                                   │
└───────────────────────────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────┐
│  GPU Worker Container (Ollama + Celery)                   │
│  ├─ Ollama Server (port 11434)                            │
│  │   └─ Models: llama2, mistral, codellama               │
│  ├─ Celery Worker                                         │
│  │   └─ Executes: ollama_llm.tasks.*                     │
│  └─ NVIDIA GPU (CUDA 12.1)                                │
└───────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Build and Start Ollama Worker

```bash
# Build Ollama-enabled worker image
docker build -f docker/Dockerfile.rufus-worker-ollama -t rufus-ollama-worker .

# Start worker with auto-pulled models
docker run -d \
    --name rufus-ollama-worker \
    --runtime=nvidia \
    --gpus all \
    -e DATABASE_URL="postgresql://rufus:secret@postgres/rufus" \
    -e CELERY_BROKER_URL="redis://redis:6379/0" \
    -e OLLAMA_MODELS="llama2,mistral,codellama" \
    -p 11434:11434 \
    rufus-ollama-worker

# Check logs
docker logs -f rufus-ollama-worker

# Expected output:
# Starting Ollama server...
# ✅ Ollama server is ready
# Pulling Ollama models: llama2,mistral,codellama
# Pulling model: llama2
# pulling manifest
# pulling 8934d96d3f08... 100% ▕████████████████▏ 3.8 GB
# ✅ llama2 pulled successfully
# Starting Celery worker...
# [celery@ollama-gpu-worker-01] ready.
```

### 2. Verify Ollama is Running

```bash
# List loaded models
curl http://localhost:11434/api/tags

# Test generation
curl http://localhost:11434/api/generate -d '{
  "model": "llama2",
  "prompt": "Why is the sky blue?",
  "stream": false
}'
```

### 3. Use in Rufus Workflow

```python
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.execution.celery import CeleryExecutionProvider
import asyncio

async def main():
    # Setup
    persistence = PostgresPersistenceProvider(db_url="postgresql://rufus:secret@localhost/rufus")
    await persistence.initialize()

    builder = WorkflowBuilder(
        config_dir="config/",
        persistence_provider=persistence,
        execution_provider=CeleryExecutionProvider(),
    )

    # Start content generation workflow
    workflow = await builder.create_workflow(
        workflow_type="OllamaContentGeneration",
        initial_data={
            "prompt": "Write a product description for a smart coffee maker with IoT features.",
            "model": "llama2",
            "max_tokens": 200,
            "temperature": 0.7,
        },
    )

    print(f"Workflow {workflow.id} started")

    # Execute (async LLM task will run on GPU worker)
    await workflow.next_step()  # Validate_Prompt
    await workflow.next_step()  # Generate_Content (GPU)

    print("LLM task dispatched to GPU worker. Waiting for completion...")

    # Poll for completion
    import time
    for _ in range(60):
        wf_dict = await persistence.load_workflow(workflow.id)
        if wf_dict["status"] == "COMPLETED":
            print("✅ Generation complete!")
            print(f"Generated text: {wf_dict['state']['generated_text']}")
            break
        time.sleep(2)

asyncio.run(main())
```

---

## Available Models

### Text Generation

| Model | Size | Description | Use Case |
|-------|------|-------------|----------|
| `llama2` | 7B | Meta's Llama 2 | General text generation |
| `llama2:13b` | 13B | Larger Llama 2 | Better quality, slower |
| `llama2:70b` | 70B | Largest Llama 2 | Highest quality |
| `llama3` | 8B | Meta's Llama 3 | Latest, best quality |
| `mistral` | 7B | Mistral AI model | Fast, high quality |
| `mixtral` | 8x7B | Mixture of experts | Complex tasks |
| `gemma:2b` | 2B | Google Gemma | Lightweight |
| `phi` | 2.7B | Microsoft Phi | Reasoning tasks |

### Code Generation

| Model | Size | Description |
|-------|------|-------------|
| `codellama` | 7B | Code generation |
| `codellama:13b` | 13B | Better code quality |
| `codellama:34b` | 34B | Production code |
| `deepseek-coder` | 6.7B | Specialized for code |

### Chat Models

| Model | Size | Description |
|-------|------|-------------|
| `llama2:chat` | 7B | Conversational Llama 2 |
| `mistral:instruct` | 7B | Instruction-following |
| `vicuna` | 7B | ChatGPT alternative |

**Full list:** https://ollama.com/library

---

## Example Tasks

### 1. Text Generation

```python
from examples.ollama_llm.tasks import generate_text

# Dispatch to GPU worker
task = generate_text.apply_async(
    kwargs={
        "state": workflow_state.model_dump(),
        "workflow_id": workflow_id,
        "prompt": "Explain quantum computing in simple terms",
        "model": "llama2",
        "max_tokens": 300,
        "temperature": 0.7,
    },
    queue="llm-inference",
)

# Wait for result
result = task.get(timeout=120)
print(result["generated_text"])
```

### 2. Chat Completion

```python
from examples.ollama_llm.tasks import chat_completion

messages = [
    {"role": "system", "content": "You are a helpful assistant specialized in fintech."},
    {"role": "user", "content": "What is a payment authorization workflow?"},
]

task = chat_completion.apply_async(
    kwargs={
        "state": state.model_dump(),
        "workflow_id": workflow_id,
        "messages": messages,
        "model": "llama2",
    },
    queue="llm-inference",
)

result = task.get(timeout=120)
print(result["assistant_message"])
```

### 3. Code Generation

```python
from examples.ollama_llm.tasks import code_generation

task = code_generation.apply_async(
    kwargs={
        "state": state.model_dump(),
        "workflow_id": workflow_id,
        "instruction": "Write a Python function to validate credit card numbers using Luhn algorithm",
        "language": "python",
        "model": "codellama",
    },
    queue="llm-inference",
)

result = task.get(timeout=120)
print(result["generated_code"])
```

### 4. Embeddings

```python
from examples.ollama_llm.tasks import embeddings

task = embeddings.apply_async(
    kwargs={
        "state": state.model_dump(),
        "workflow_id": workflow_id,
        "text": "Machine learning workflow automation",
        "model": "llama2",
    },
    queue="llm-inference",
)

result = task.get(timeout=30)
embedding_vector = result["embedding"]  # List[float] with 4096 dimensions
```

---

## Production Configuration

### Docker Compose

```yaml
version: '3.8'

services:
  ollama-gpu-worker:
    build:
      context: ..
      dockerfile: docker/Dockerfile.rufus-worker-ollama
    runtime: nvidia
    environment:
      # GPU
      NVIDIA_VISIBLE_DEVICES: all
      CUDA_VISIBLE_DEVICES: "0"

      # Database and Celery
      DATABASE_URL: "postgresql://rufus:secret@postgres/rufus"
      CELERY_BROKER_URL: "redis://redis:6379/0"
      CELERY_RESULT_BACKEND: "redis://redis:6379/0"

      # Worker config
      WORKER_ID: "ollama-gpu-worker-01"
      WORKER_REGION: "us-east-1"
      WORKER_CONCURRENCY: "1"  # 1 for large models (70B), 2-4 for small (7B)
      WORKER_POOL: "solo"

      # Ollama config
      OLLAMA_MODELS: "llama2,mistral,codellama"  # Auto-pull on startup
      OLLAMA_HOST: "0.0.0.0:11434"
      OLLAMA_NUM_PARALLEL: "1"  # Number of parallel requests

    ports:
      - "11434:11434"  # Ollama API

    volumes:
      - ollama_models:/root/.ollama  # Persist downloaded models
      - ../config:/app/config

    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

volumes:
  ollama_models:
    driver: local
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rufus-ollama-worker
spec:
  replicas: 1
  selector:
    matchLabels:
      app: rufus-ollama-worker
  template:
    metadata:
      labels:
        app: rufus-ollama-worker
    spec:
      nodeSelector:
        cloud.google.com/gke-accelerator: nvidia-tesla-t4

      containers:
      - name: worker
        image: rufus-ollama-worker:latest
        env:
        - name: OLLAMA_MODELS
          value: "llama2,mistral"
        - name: WORKER_CONCURRENCY
          value: "2"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: rufus-secrets
              key: database-url

        ports:
        - containerPort: 11434
          name: ollama-api

        resources:
          limits:
            nvidia.com/gpu: 1
            memory: "16Gi"
          requests:
            nvidia.com/gpu: 1
            memory: "8Gi"

        volumeMounts:
        - name: ollama-models
          mountPath: /root/.ollama

      volumes:
      - name: ollama-models
        persistentVolumeClaim:
          claimName: ollama-models-pvc
```

---

## Performance Tuning

### Model Quantization

Ollama automatically uses quantization for faster inference:

```bash
# 4-bit quantized (fastest, lowest memory)
ollama pull llama2:7b-q4_0

# 5-bit quantized (balanced)
ollama pull llama2:7b-q5_1

# 8-bit quantized (high quality)
ollama pull llama2:7b-q8_0

# Full precision (highest quality, slowest)
ollama pull llama2:7b-fp16
```

### Concurrency

```bash
# Small models (7B): 2-4 concurrent requests
export WORKER_CONCURRENCY=4
export OLLAMA_NUM_PARALLEL=4

# Medium models (13B): 2 concurrent requests
export WORKER_CONCURRENCY=2
export OLLAMA_NUM_PARALLEL=2

# Large models (70B): 1 request at a time
export WORKER_CONCURRENCY=1
export OLLAMA_NUM_PARALLEL=1
```

### GPU Memory

| Model Size | VRAM Required | Recommended GPU |
|-----------|---------------|-----------------|
| 2B-3B | 4GB | RTX 3060, T4 |
| 7B | 8GB | RTX 3070, L4 |
| 13B | 16GB | RTX 4090, V100 |
| 70B | 48GB+ | A100 (40GB/80GB) |

### Inference Speed

On NVIDIA RTX 4090 (24GB VRAM):

| Model | Tokens/sec | Time for 200 tokens |
|-------|-----------|---------------------|
| `llama2:7b-q4_0` | ~45 | 4.4s |
| `llama2:7b-q8_0` | ~35 | 5.7s |
| `llama2:13b-q4_0` | ~28 | 7.1s |
| `codellama:34b-q4_0` | ~12 | 16.7s |

---

## Cost Comparison

**Ollama (Self-Hosted GPU)** vs **OpenAI API**:

| Metric | Ollama (RTX 4090) | OpenAI GPT-3.5 Turbo |
|--------|------------------|---------------------|
| **Hardware cost** | $1,600 one-time | $0 |
| **Cost per 1M tokens** | ~$3 (electricity)* | $1.50 (input) + $2.00 (output) |
| **Latency** | 50-200ms (local) | 500-2000ms (API) |
| **Privacy** | 100% local | Sent to OpenAI |
| **Offline** | ✅ Works offline | ❌ Requires internet |
| **Customization** | ✅ Fine-tune models | ❌ Limited |

*Based on $0.10/kWh electricity, 350W GPU @ 50% utilization

**Break-even point:** ~500M tokens (~500,000 workflow executions)

---

## Monitoring

### Ollama API Health

```bash
# Check loaded models
curl http://localhost:11434/api/tags | jq '.models[].name'

# Monitor Ollama logs
docker logs -f rufus-ollama-worker | grep -i ollama
```

### GPU Utilization

```bash
# Real-time GPU monitoring
nvidia-smi -l 1

# Expected during inference:
# GPU Utilization: 95-100%
# Memory Usage: 8-40GB (depending on model)
# Power: 250-350W
```

### Celery Metrics

```bash
# Active tasks
celery -A rufus.celery_app inspect active

# Task stats
celery -A rufus.celery_app inspect stats

# Worker registered queues
celery -A rufus.celery_app inspect active_queues
```

---

## Troubleshooting

**Problem:** Ollama server not starting
```bash
# Check if port 11434 is available
netstat -tuln | grep 11434

# Check Ollama logs
docker exec rufus-ollama-worker journalctl -u ollama

# Manual start
docker exec -it rufus-ollama-worker ollama serve
```

**Problem:** Model not found
```bash
# Pull model manually
docker exec rufus-ollama-worker ollama pull llama2

# List available models
docker exec rufus-ollama-worker ollama list
```

**Problem:** Out of GPU memory
```bash
# Use smaller model
ollama pull llama2:7b-q4_0  # Instead of llama2:70b

# Reduce concurrency
export WORKER_CONCURRENCY=1

# Stop other GPU processes
nvidia-smi | grep python  # Find PIDs
kill <PID>
```

**Problem:** Slow inference
```bash
# Check GPU is being used
nvidia-smi

# If GPU util is 0%, Ollama may be using CPU
docker exec rufus-ollama-worker env | grep CUDA_VISIBLE_DEVICES

# Should be: CUDA_VISIBLE_DEVICES=0
```

---

## Summary

✅ Ollama server running on GPU worker
✅ Models auto-pulled on startup
✅ Celery tasks route to `llm-inference` queue
✅ Simple Python API for LLM inference
✅ 50+ models available (Llama, Mistral, CodeLlama, etc.)
✅ Production-ready Docker + Kubernetes deployment

**Your local LLM inference system is ready!** 🚀

**Next:** See [GPU_QUICKSTART.md](./GPU_QUICKSTART.md) for end-to-end workflow examples.
