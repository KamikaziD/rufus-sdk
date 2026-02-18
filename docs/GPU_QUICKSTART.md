# GPU AI Inference Quick Start Guide

**5-minute guide** to deploy GPU-enabled Celery workers for AI inference with Rufus.

## Prerequisites

1. **NVIDIA GPU** with CUDA support (any modern GPU: RTX 3060+, Tesla T4+, etc.)
2. **NVIDIA Drivers** installed (version 535+ for CUDA 12.1)
3. **Docker** with **nvidia-docker runtime**

## Verify GPU Access

```bash
# Check GPU is visible
nvidia-smi

# Expected output:
# +-----------------------------------------------------------------------------+
# | NVIDIA-SMI 535.86.10    Driver Version: 535.86.10    CUDA Version: 12.2   |
# +-----------------------------------------------------------------------------+
# | GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
# +-------------------------------+----------------------+----------------------+
# |   0  NVIDIA GeForce...  Off  | 00000000:01:00.0 Off |                  N/A |
# +-------------------------------+----------------------+----------------------+

# Verify nvidia-docker runtime
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

## Step 1: Start Rufus with GPU Worker

```bash
# Clone and navigate to repo
cd rufus-sdk

# Start all services (includes GPU worker)
docker-compose -f docker/docker-compose.gpu.yml up -d

# Verify services are running
docker-compose -f docker/docker-compose.gpu.yml ps

# Expected output:
# NAME                IMAGE                              STATUS
# rufus-postgres      postgres:15-alpine                 Up
# rufus-redis         redis:7-alpine                     Up
# rufus-server        rufus-server-local                 Up
# rufus-gpu-worker    rufus-worker-gpu                   Up
# rufus-cpu-worker-1  rufus-worker-local                 Up
# rufus-flower        mher/flower:2.0                    Up
```

## Step 2: Verify GPU Worker Registration

```bash
# Check GPU worker logs
docker logs rufus-gpu-worker

# Expected output:
# [INFO] Worker gpu-worker-01 registered successfully in region us-east-1
# [INFO] CUDA initialized: NVIDIA GeForce RTX 3090
# [INFO] Initialized all providers for worker
# [celery@gpu-worker-01] ready.

# Query worker database (from postgres container)
docker exec rufus-postgres psql -U rufus -d rufus_production -c \
  "SELECT worker_id, hostname, capabilities->>'gpu_model' AS gpu FROM worker_nodes WHERE capabilities->>'gpu' = 'true';"

# Expected output:
# worker_id      | hostname              | gpu
# ---------------|-----------------------|------------------
# gpu-worker-01  | a1b2c3d4e5f6          | NVIDIA GPU
```

## Step 3: Create AI Inference Workflow

**File:** `config/sentiment_analysis.yaml`

```yaml
workflow_type: "SentimentAnalysis"
workflow_version: "1.0.0"
description: "GPU-accelerated sentiment analysis using transformer model"
initial_state_model: "examples.sentiment.models.SentimentState"

steps:
  # Step 1: Validate input text
  - name: "Validate_Input"
    type: "STANDARD"
    function: "examples.sentiment.steps.validate_input"
    automate_next: true

  # Step 2: Run sentiment analysis on GPU
  - name: "Analyze_Sentiment"
    type: "ASYNC"
    function: "examples.sentiment.tasks.analyze_sentiment_gpu"
    description: "GPU-accelerated transformer inference"
    automate_next: true

  # Step 3: Format and return result
  - name: "Format_Result"
    type: "STANDARD"
    function: "examples.sentiment.steps.format_result"
```

**File:** `examples/sentiment/models.py`

```python
from pydantic import BaseModel
from typing import Optional

class SentimentState(BaseModel):
    """State for sentiment analysis workflow."""
    text: str
    sentiment: Optional[str] = None  # "positive", "negative", "neutral"
    confidence: Optional[float] = None
    inference_time_ms: Optional[float] = None
```

**File:** `examples/sentiment/tasks.py`

```python
"""GPU-accelerated sentiment analysis tasks."""
from rufus.celery_app import celery_app
import logging

logger = logging.getLogger(__name__)


@celery_app.task(
    name="examples.sentiment.tasks.analyze_sentiment_gpu",
    bind=True,
    queue="gpu-inference",  # Route to GPU workers
    time_limit=30,
)
def analyze_sentiment_gpu(self, state: dict, workflow_id: str):
    """
    Run sentiment analysis using GPU-accelerated transformer.

    This task runs on GPU workers with PyTorch + Transformers installed.
    """
    import time
    import torch
    from transformers import pipeline

    logger.info(f"GPU Sentiment analysis: workflow={workflow_id}")

    # Check GPU availability
    device = 0 if torch.cuda.is_available() else -1
    logger.info(f"Using device: {'GPU' if device == 0 else 'CPU'}")

    # Load sentiment analysis pipeline (cached after first use)
    classifier = pipeline(
        "sentiment-analysis",
        model="distilbert-base-uncased-finetuned-sst-2-english",
        device=device,
    )

    # Run inference
    start_time = time.perf_counter()
    result = classifier(state["text"])[0]
    inference_time = (time.perf_counter() - start_time) * 1000

    logger.info(
        f"Sentiment: {result['label']} "
        f"(confidence={result['score']:.2f}, time={inference_time:.2f}ms)"
    )

    return {
        "sentiment": result["label"].lower(),  # "positive" or "negative"
        "confidence": result["score"],
        "inference_time_ms": inference_time,
    }
```

**File:** `examples/sentiment/steps.py`

```python
"""Sentiment analysis workflow steps."""
from rufus.models import StepContext
from examples.sentiment.models import SentimentState


def validate_input(state: SentimentState, context: StepContext) -> dict:
    """Validate input text."""
    if not state.text or len(state.text) < 3:
        raise ValueError("Text must be at least 3 characters")

    if len(state.text) > 1000:
        raise ValueError("Text too long (max 1000 characters)")

    return {}


def format_result(state: SentimentState, context: StepContext) -> dict:
    """Format final result."""
    return {
        "result": {
            "text": state.text,
            "sentiment": state.sentiment,
            "confidence": round(state.confidence, 3),
            "inference_time_ms": round(state.inference_time_ms, 2),
        }
    }
```

## Step 4: Run the Workflow

```python
# In Python REPL or script
from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.execution.celery import CeleryExecutionProvider
from rufus.implementations.observability.logging import LoggingObserver
import asyncio

async def main():
    # Initialize providers
    persistence = PostgresPersistenceProvider(
        db_url="postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_production"
    )
    await persistence.initialize()

    execution = CeleryExecutionProvider()
    observer = LoggingObserver()

    # Create workflow builder
    builder = WorkflowBuilder(
        config_dir="config/",
        persistence_provider=persistence,
        execution_provider=execution,
        observer=observer,
    )

    # Start sentiment analysis workflow
    workflow = await builder.create_workflow(
        workflow_type="SentimentAnalysis",
        initial_data={
            "text": "This product is absolutely amazing! Best purchase ever!"
        },
    )

    print(f"Workflow started: {workflow.id}")

    # Execute first step (validation)
    await workflow.next_step()

    # This triggers GPU inference task (async)
    await workflow.next_step()

    print(f"GPU inference task dispatched. Status: {workflow.status}")
    print("Task will complete on GPU worker and resume workflow automatically.")

    # Wait for completion
    import time
    for _ in range(30):
        workflow_dict = await persistence.load_workflow(workflow.id)
        if workflow_dict["status"] == "COMPLETED":
            print(f"✅ Workflow completed!")
            print(f"Result: {workflow_dict['state']}")
            break
        print(f"Status: {workflow_dict['status']}")
        time.sleep(1)

# Run
asyncio.run(main())
```

**Expected output:**

```
Workflow started: 550e8400-e29b-41d4-a716-446655440000
Status: PENDING_ASYNC
GPU inference task dispatched. Status: PENDING_ASYNC
Task will complete on GPU worker and resume workflow automatically.
Status: PENDING_ASYNC
Status: ACTIVE
✅ Workflow completed!
Result: {
  "text": "This product is absolutely amazing! Best purchase ever!",
  "sentiment": "positive",
  "confidence": 0.999,
  "inference_time_ms": 45.23,
  "result": {
    "text": "This product is absolutely amazing! Best purchase ever!",
    "sentiment": "positive",
    "confidence": 0.999,
    "inference_time_ms": 45.23
  }
}
```

## Step 5: Monitor GPU Workers

**Celery Flower UI:**
```bash
# Open in browser
open http://localhost:5555

# Login: admin / rufus2024
```

**GPU utilization:**
```bash
# Monitor GPU in real-time
watch -n 1 nvidia-smi

# Expected output during inference:
# +-----------------------------------------------------------------------------+
# |   0  NVIDIA GeForce...   On   | 00000000:01:00.0 Off |                  N/A |
# | 45%   62C    P2   145W / 350W |   3240MiB / 24576MiB |     87%      Default |
# +-----------------------------------------------------------------------------+
```

**Celery worker stats:**
```bash
# Inspect active tasks
docker exec rufus-gpu-worker celery -A rufus.celery_app inspect active

# Worker stats
docker exec rufus-gpu-worker celery -A rufus.celery_app inspect stats
```

## Advanced: Custom LLM Inference

For **large language models** (Llama, Mistral, GPT-style models), modify the task:

```python
@celery_app.task(
    name="examples.llm.tasks.generate_text_gpu",
    bind=True,
    queue="gpu-inference",
    time_limit=120,  # 2 minutes for LLM inference
)
def generate_text_gpu(self, state: dict, workflow_id: str, prompt: str):
    """Generate text using GPU-accelerated LLM."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_name = "meta-llama/Llama-2-7b-chat-hf"  # Requires HuggingFace token

    # Load model (cached after first load)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.float16,  # FP16 for faster inference
        device_map="auto",  # Automatically use GPU
    )

    # Generate
    inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
    outputs = model.generate(
        **inputs,
        max_new_tokens=200,
        temperature=0.7,
        do_sample=True,
    )

    generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

    return {"generated_text": generated_text}
```

## Troubleshooting

**GPU not detected:**
```bash
# Check Docker can see GPU
docker run --rm --gpus all nvidia/cuda:12.1.0-base nvidia-smi

# If fails: Install nvidia-docker2
sudo apt-get install nvidia-docker2
sudo systemctl restart docker
```

**Worker not registering:**
```bash
# Check worker logs
docker logs rufus-gpu-worker

# Verify DATABASE_URL is correct
docker exec rufus-gpu-worker env | grep DATABASE_URL
```

**Tasks not routing to GPU worker:**
```bash
# Check queue binding
docker exec rufus-gpu-worker celery -A rufus.celery_app inspect active_queues

# Expected: ['gpu-inference', 'gpu-training']
```

**Out of GPU memory:**
```bash
# Reduce worker concurrency
docker-compose -f docker/docker-compose.gpu.yml down
# Edit docker-compose.gpu.yml: WORKER_CONCURRENCY: "1"
docker-compose -f docker/docker-compose.gpu.yml up -d gpu-worker
```

## Next Steps

- **See full guide:** [GPU_AI_INFERENCE_GUIDE.md](./GPU_AI_INFERENCE_GUIDE.md)
- **Deploy to production:** See Kubernetes manifests in the full guide
- **Custom models:** Add your ONNX/PyTorch models to `models/` directory
- **Monitor costs:** Track GPU utilization vs. CPU cost tradeoffs

## Summary

✅ GPU worker deployed with CUDA 12.1 + PyTorch
✅ Task routing to `gpu-inference` queue
✅ Worker capabilities tracked in PostgreSQL
✅ Sentiment analysis workflow running on GPU
✅ Automatic workflow resumption after GPU task completion

**Your GPU-enabled AI inference system is ready!** 🚀
