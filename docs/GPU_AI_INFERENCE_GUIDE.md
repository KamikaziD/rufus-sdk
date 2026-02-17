# GPU-Enabled AI Inference with Rufus + Celery

This guide shows how to deploy Celery workers with GPU capabilities to execute AI inference steps on GPU servers running local models.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  WORKFLOW ORCHESTRATION                     │
├─────────────────────────────────────────────────────────────┤
│  Workflow YAML (config/)                                    │
│  ├─ Step: "Detect_Fraud"                                    │
│  │   type: AI_INFERENCE                                     │
│  │   ai_config:                                             │
│  │     model_name: "fraud_detector"                         │
│  │     runtime: "onnx"                                      │
│  │   worker_queue: "gpu-inference"  ← Route to GPU workers  │
│  └─ ...                                                      │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                CELERY TASK QUEUE (Redis)                    │
├─────────────────────────────────────────────────────────────┤
│  Queues:                                                    │
│  ├─ default (CPU workers)                                   │
│  ├─ gpu-inference (GPU workers)                             │
│  └─ gpu-training (GPU workers)                              │
└─────────────────────────────────────────────────────────────┘
        │                                    │
        ▼                                    ▼
┌──────────────────┐          ┌─────────────────────────────┐
│  CPU Workers     │          │  GPU Workers (NVIDIA)       │
│  (Standard)      │          │  ├─ CUDA 12.1               │
│  • Payment       │          │  ├─ PyTorch + Transformers   │
│  • Validation    │          │  ├─ ONNX Runtime GPU         │
│  • HTTP calls    │          │  ├─ TensorRT                 │
└──────────────────┘          │  └─ 24GB VRAM               │
                              └─────────────────────────────┘
```

---

## Step 1: Install GPU Dependencies on Worker Server

**On your GPU server** (e.g., AWS p3.2xlarge, GCP n1-standard-8-nvidia-tesla-v100):

```bash
# 1. Verify NVIDIA GPU
nvidia-smi

# Expected output:
# +-----------------------------------------------------------------------------+
# | NVIDIA-SMI 535.86.10    Driver Version: 535.86.10    CUDA Version: 12.2   |
# |-------------------------------+----------------------+----------------------+
# | GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
# | Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
# |===============================+======================+======================|
# |   0  Tesla V100-SXM2...  Off  | 00000000:00:1E.0 Off |                    0 |
# | N/A   35C    P0    42W / 300W |      0MiB / 16160MiB |      0%      Default |
# +-------------------------------+----------------------+----------------------+

# 2. Install CUDA Toolkit (if not already installed)
wget https://developer.download.nvidia.com/compute/cuda/12.1.0/local_installers/cuda_12.1.0_530.30.02_linux.run
sudo sh cuda_12.1.0_530.30.02_linux.run --silent --toolkit

# 3. Install Rufus SDK with GPU dependencies
pip install -r requirements.txt

# 4. Install ONNX Runtime GPU (for ONNX models)
pip install onnxruntime-gpu==1.18.1

# 5. Install PyTorch GPU (for Transformers/LLMs)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 6. Install Transformers (for LLMs like Llama, GPT, BERT)
pip install transformers accelerate bitsandbytes

# 7. Verify GPU is accessible from Python
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}, Device count: {torch.cuda.device_count()}')"
# Expected: CUDA available: True, Device count: 1

python -c "import onnxruntime as ort; print(f'ONNX GPU providers: {ort.get_available_providers()}')"
# Expected: ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
```

---

## Step 2: Configure Worker with GPU Capabilities

**Set environment variables** before starting the Celery worker:

```bash
# Worker identity
export WORKER_ID="gpu-worker-01"
export WORKER_REGION="us-east-1"
export WORKER_ZONE="us-east-1a"

# GPU capabilities (stored in PostgreSQL worker_nodes table)
export WORKER_CAPABILITIES='{
  "gpu": true,
  "gpu_model": "Tesla V100",
  "vram_gb": 16,
  "cuda_version": "12.1",
  "pytorch_version": "2.0.1",
  "onnx_gpu": true,
  "tensorrt": true,
  "transformers": true,
  "max_batch_size": 32
}'

# Database connection (for worker registry)
export DATABASE_URL="postgresql://rufus:secret@db.example.com:5432/rufus_cloud"

# Celery broker
export CELERY_BROKER_URL="redis://redis.example.com:6379/0"
export CELERY_RESULT_BACKEND="redis://redis.example.com:6379/0"
```

---

## Step 3: Start GPU Worker with Queue Routing

**Start the worker listening to GPU-specific queues:**

```bash
# Listen ONLY to gpu-inference queue (recommended for dedicated GPU servers)
celery -A rufus.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --pool=solo \
    -Q gpu-inference \
    -n gpu-worker-01@%h

# Explanation:
# --concurrency=2:     Run 2 concurrent tasks (adjust based on GPU memory)
# --pool=solo:         Single-threaded execution (safer for GPU memory)
# -Q gpu-inference:    Only process tasks from 'gpu-inference' queue
# -n gpu-worker-01@%h: Unique worker name for monitoring
```

**Alternative:** Listen to multiple queues with priority:

```bash
celery -A rufus.celery_app worker \
    --loglevel=info \
    --concurrency=4 \
    -Q gpu-inference:10,gpu-training:5,default:1 \
    -n gpu-worker-01@%h

# Priority routing:
# gpu-inference:10 = Highest priority (inference is fast)
# gpu-training:5   = Medium priority (training is slow)
# default:1        = Lowest priority (fallback for standard tasks)
```

---

## Step 4: Create Custom Inference Provider for GPU Models

For **LLM inference** or **custom PyTorch models**, create a custom inference provider:

**File:** `my_app/inference/llm_provider.py`

```python
"""
Custom LLM Inference Provider for Rufus
Supports: Llama, Mistral, GPT-style models via Transformers
"""
import logging
import torch
from typing import Dict, Any
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

from rufus.providers.inference import (
    InferenceProvider,
    InferenceRuntime,
    InferenceResult,
    ModelMetadata,
)

logger = logging.getLogger(__name__)


class LLMInferenceProvider(InferenceProvider):
    """
    Inference provider for large language models using Hugging Face Transformers.

    Supports:
    - GPT-style models (Llama 2, Mistral, Falcon, etc.)
    - BERT-style models (for embeddings/classification)
    - Vision-language models (CLIP, BLIP)

    GPU acceleration via CUDA/MPS automatically enabled.
    """

    def __init__(
        self,
        device: str = "auto",
        torch_dtype: str = "float16",
        use_flash_attention: bool = True,
    ):
        """
        Args:
            device: Device for inference ('cuda', 'cpu', 'mps', or 'auto')
            torch_dtype: Data type for model weights ('float16', 'bfloat16', 'float32')
            use_flash_attention: Enable Flash Attention 2 for faster inference
        """
        self._runtime = InferenceRuntime.CUSTOM
        self._models: Dict[str, Any] = {}
        self._tokenizers: Dict[str, Any] = {}
        self._pipelines: Dict[str, Any] = {}

        # Auto-detect best device
        if device == "auto":
            if torch.cuda.is_available():
                self._device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                self._device = "mps"
            else:
                self._device = "cpu"
        else:
            self._device = device

        # Convert dtype string to torch dtype
        dtype_map = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        self._torch_dtype = dtype_map.get(torch_dtype, torch.float16)
        self._use_flash_attention = use_flash_attention

        logger.info(
            f"LLMInferenceProvider initialized: "
            f"device={self._device}, dtype={torch_dtype}, "
            f"flash_attention={use_flash_attention}"
        )

    @property
    def runtime(self) -> InferenceRuntime:
        return self._runtime

    async def initialize(self) -> None:
        """Initialize provider (GPU warmup)."""
        if self._device == "cuda":
            # Warm up CUDA
            torch.cuda.init()
            logger.info(f"CUDA initialized: {torch.cuda.get_device_name(0)}")

    async def close(self) -> None:
        """Clean up loaded models."""
        self._models.clear()
        self._tokenizers.clear()
        self._pipelines.clear()
        if self._device == "cuda":
            torch.cuda.empty_cache()

    def is_model_loaded(self, model_name: str) -> bool:
        """Check if model is already loaded."""
        return model_name in self._models

    async def load_model(
        self,
        model_path: str,
        model_name: str,
        model_version: str = "1.0.0",
        metadata: Dict[str, Any] = None,
    ) -> ModelMetadata:
        """
        Load a Hugging Face model.

        Args:
            model_path: Hugging Face model ID (e.g., "meta-llama/Llama-2-7b-chat-hf")
                        or local path to model directory
            model_name: Friendly name for the model
            model_version: Version string
            metadata: Additional metadata (task_type, max_tokens, etc.)
        """
        metadata = metadata or {}
        task_type = metadata.get("task_type", "text-generation")

        logger.info(f"Loading LLM model: {model_path} (task: {task_type})")

        # Load tokenizer
        tokenizer = AutoTokenizer.from_pretrained(model_path)

        # Load model with GPU optimizations
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=self._torch_dtype,
            device_map=self._device if self._device != "auto" else "auto",
            use_flash_attention_2=self._use_flash_attention,
            low_cpu_mem_usage=True,
        )

        # Create pipeline for easy inference
        pipe = pipeline(
            task_type,
            model=model,
            tokenizer=tokenizer,
            device=0 if self._device == "cuda" else -1,
            torch_dtype=self._torch_dtype,
        )

        # Cache
        self._models[model_name] = model
        self._tokenizers[model_name] = tokenizer
        self._pipelines[model_name] = pipe

        # Get model info
        param_count = sum(p.numel() for p in model.parameters()) / 1e9

        model_metadata = ModelMetadata(
            name=model_name,
            version=model_version,
            runtime=self._runtime.value,
            path=model_path,
            input_shape={"prompt": "text"},
            output_shape={"generated_text": "text"},
            metadata={
                "task_type": task_type,
                "parameters_billion": round(param_count, 2),
                "device": str(self._device),
                "dtype": str(self._torch_dtype),
                **metadata,
            },
        )

        logger.info(
            f"Model loaded: {model_name} "
            f"({param_count:.2f}B params, {self._device})"
        )

        return model_metadata

    async def unload_model(self, model_name: str) -> None:
        """Unload model from memory."""
        if model_name in self._models:
            del self._models[model_name]
            del self._tokenizers[model_name]
            del self._pipelines[model_name]

            if self._device == "cuda":
                torch.cuda.empty_cache()

            logger.info(f"Model unloaded: {model_name}")

    def get_model_metadata(self, model_name: str) -> ModelMetadata:
        """Get metadata for loaded model."""
        if model_name not in self._models:
            raise ValueError(f"Model not loaded: {model_name}")

        model = self._models[model_name]
        param_count = sum(p.numel() for p in model.parameters()) / 1e9

        return ModelMetadata(
            name=model_name,
            version="1.0.0",
            runtime=self._runtime.value,
            path="unknown",
            input_shape={"prompt": "text"},
            output_shape={"generated_text": "text"},
            metadata={
                "parameters_billion": round(param_count, 2),
                "device": str(self._device),
            },
        )

    async def run_inference(
        self,
        model_name: str,
        inputs: Dict[str, Any],
    ) -> InferenceResult:
        """
        Run LLM inference.

        Args:
            model_name: Name of loaded model
            inputs: Dict with 'prompt' key (str) and optional generation params

        Returns:
            InferenceResult with generated text
        """
        import time

        if model_name not in self._pipelines:
            return InferenceResult(
                success=False,
                error_message=f"Model not loaded: {model_name}",
                outputs={},
                inference_time_ms=0,
                model_name=model_name,
                model_version="unknown",
            )

        pipe = self._pipelines[model_name]
        prompt = inputs.get("prompt", "")

        # Extract generation parameters
        max_new_tokens = inputs.get("max_tokens", inputs.get("max_new_tokens", 100))
        temperature = inputs.get("temperature", 0.7)
        top_p = inputs.get("top_p", 0.9)
        do_sample = inputs.get("do_sample", True)

        start_time = time.perf_counter()

        try:
            # Run inference
            result = pipe(
                prompt,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=do_sample,
                return_full_text=False,  # Only return generated text
            )

            inference_time = (time.perf_counter() - start_time) * 1000

            # Extract generated text
            if isinstance(result, list):
                generated_text = result[0]["generated_text"]
            else:
                generated_text = result["generated_text"]

            return InferenceResult(
                success=True,
                outputs={"generated_text": generated_text},
                inference_time_ms=inference_time,
                model_name=model_name,
                model_version="1.0.0",
            )

        except Exception as e:
            logger.exception(f"Inference failed for model {model_name}")
            inference_time = (time.perf_counter() - start_time) * 1000

            return InferenceResult(
                success=False,
                error_message=str(e),
                outputs={},
                inference_time_ms=inference_time,
                model_name=model_name,
                model_version="1.0.0",
            )


def is_llm_available() -> bool:
    """Check if LLM dependencies are installed."""
    try:
        import transformers
        import torch
        return True
    except ImportError:
        return False
```

**Register the provider** in your worker initialization:

```python
# my_app/worker_init.py
from rufus_edge.inference_executor import get_inference_executor
from my_app.inference.llm_provider import LLMInferenceProvider

async def initialize_gpu_worker():
    """Initialize GPU worker with LLM support."""
    executor = get_inference_executor()

    # Register LLM provider
    llm_provider = LLMInferenceProvider(
        device="cuda",
        torch_dtype="float16",
        use_flash_attention=True,
    )
    executor.register_provider(llm_provider)

    # Load models (once at startup)
    await executor.initialize()

    # Pre-load common models
    await llm_provider.load_model(
        model_path="meta-llama/Llama-2-7b-chat-hf",
        model_name="llama2-7b-chat",
        model_version="2.0.0",
        metadata={"task_type": "text-generation"},
    )

    print("GPU worker ready with LLM support")
```

---

## Step 5: Create AI Inference Workflow

**Workflow YAML** using GPU-routed AI inference:

**File:** `config/fraud_detection_workflow.yaml`

```yaml
workflow_type: "FraudDetection"
workflow_version: "2.0.0"
description: "Real-time fraud detection using GPU-accelerated AI"
initial_state_model: "my_app.models.FraudDetectionState"

steps:
  # Step 1: Validate transaction data
  - name: "Validate_Transaction"
    type: "STANDARD"
    function: "my_app.steps.validate_transaction"
    automate_next: true

  # Step 2: Extract features from transaction
  - name: "Extract_Features"
    type: "STANDARD"
    function: "my_app.steps.extract_features"
    description: "Convert transaction to ML features"
    automate_next: true

  # Step 3: Run fraud detection model on GPU worker
  - name: "Detect_Fraud"
    type: "AI_INFERENCE"
    description: "GPU-accelerated fraud detection via ONNX model"
    ai_config:
      model_name: "fraud_detector_v2"
      model_path: "models/fraud_detector_fp16.onnx"
      runtime: "onnx"  # Uses onnxruntime-gpu
      input_source: "state.features"
      preprocessing: "normalize"
      preprocessing_params:
        mean: 0.0
        std: 1.0
      output_key: "fraud_score"
      postprocessing: "binary"
      postprocessing_params:
        threshold: 0.85
      threshold: 0.85
      threshold_key: "score"
      fallback_on_error: "default"
      default_result:
        score: 0.5
        prediction: false
        confidence: 0.0
      timeout_ms: 2000
    # CRITICAL: Route to GPU queue
    worker_queue: "gpu-inference"
    automate_next: true

  # Step 4: Decision routing based on fraud score
  - name: "Route_By_Score"
    type: "DECISION"
    function: "my_app.steps.route_by_fraud_score"
    routes:
      - condition: "state.fraud_score.prediction == true"
        target: "Block_Transaction"
      - condition: "state.fraud_score.score > 0.7"
        target: "Manual_Review"
      - condition: "state.fraud_score.score <= 0.7"
        target: "Approve_Transaction"

  # Step 5a: Block high-risk transaction
  - name: "Block_Transaction"
    type: "STANDARD"
    function: "my_app.steps.block_transaction"
    description: "Immediate block for fraud"

  # Step 5b: Queue for manual review
  - name: "Manual_Review"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.queue_for_review"
    description: "Suspicious - needs human review"

  # Step 5c: Approve low-risk transaction
  - name: "Approve_Transaction"
    type: "STANDARD"
    function: "my_app.steps.approve_transaction"
    description: "Approve legitimate transaction"
```

---

## Step 6: Implement Celery Task for AI Inference

For **custom routing logic** or **async AI tasks**, create Celery tasks:

**File:** `my_app/ai_tasks.py`

```python
"""
GPU-accelerated AI inference tasks for Celery workers.
"""
from rufus.celery_app import celery_app
from rufus_edge.inference_executor import get_inference_executor
from rufus.models import AIInferenceConfig, StepContext
import logging

logger = logging.getLogger(__name__)


@celery_app.task(
    name="my_app.ai_tasks.run_llm_inference",
    bind=True,
    max_retries=2,
    time_limit=60,  # 60 second hard limit
    soft_time_limit=50,  # Warning at 50 seconds
)
def run_llm_inference(self, state: dict, workflow_id: str, prompt: str, **kwargs):
    """
    Run LLM inference on GPU worker.

    Args:
        state: Workflow state dict
        workflow_id: Workflow UUID
        prompt: Input prompt for LLM
        **kwargs: Additional generation params (max_tokens, temperature, etc.)

    Returns:
        Dict with generated_text and metadata
    """
    import asyncio
    from rufus.utils.postgres_executor import pg_executor

    logger.info(
        f"LLM inference task started: workflow={workflow_id}, "
        f"prompt_length={len(prompt)}"
    )

    async def _run_inference():
        executor = get_inference_executor()
        provider = executor.get_provider("custom")  # LLMInferenceProvider

        if not provider:
            raise RuntimeError("LLM inference provider not available")

        result = await provider.run_inference(
            model_name=kwargs.get("model_name", "llama2-7b-chat"),
            inputs={
                "prompt": prompt,
                "max_tokens": kwargs.get("max_tokens", 200),
                "temperature": kwargs.get("temperature", 0.7),
                "top_p": kwargs.get("top_p", 0.9),
            },
        )

        if not result.success:
            raise RuntimeError(f"LLM inference failed: {result.error_message}")

        return {
            "generated_text": result.outputs["generated_text"],
            "inference_time_ms": result.inference_time_ms,
            "model_name": result.model_name,
        }

    # Run async inference synchronously (Celery tasks are sync)
    result = pg_executor.run_coroutine_sync(_run_inference())

    logger.info(
        f"LLM inference completed: workflow={workflow_id}, "
        f"time={result['inference_time_ms']:.2f}ms"
    )

    return result


@celery_app.task(
    name="my_app.ai_tasks.run_batch_inference",
    bind=True,
    time_limit=300,  # 5 minutes for batch processing
)
def run_batch_inference(self, batch_data: list, model_name: str, **kwargs):
    """
    Run batch inference on GPU worker.

    Optimized for throughput - processes multiple inputs in a single GPU call.

    Args:
        batch_data: List of input dicts
        model_name: Model to use for inference
        **kwargs: Additional model parameters

    Returns:
        List of inference results
    """
    import asyncio
    from rufus.utils.postgres_executor import pg_executor

    logger.info(f"Batch inference started: {len(batch_data)} items, model={model_name}")

    async def _run_batch():
        executor = get_inference_executor()
        provider = executor.get_provider("onnx")  # ONNX Runtime GPU

        results = []
        for item in batch_data:
            result = await provider.run_inference(
                model_name=model_name,
                inputs=item,
            )
            results.append(result.outputs if result.success else None)

        return results

    results = pg_executor.run_coroutine_sync(_run_batch())

    logger.info(f"Batch inference completed: {len(results)} results")
    return results
```

**Route the task to GPU queue:**

```python
# In your workflow step function
from my_app.ai_tasks import run_llm_inference

def generate_summary(state: MyState, context: StepContext):
    """Generate AI summary of transaction (GPU-accelerated)."""

    # Dispatch to GPU queue
    task = run_llm_inference.apply_async(
        kwargs={
            "state": state.model_dump(),
            "workflow_id": context.workflow_id,
            "prompt": f"Summarize this transaction: {state.transaction_details}",
            "max_tokens": 100,
            "temperature": 0.3,
        },
        queue="gpu-inference",  # Route to GPU workers
        priority=5,  # Higher priority for user-facing tasks
    )

    # Store task ID for tracking
    state.llm_task_id = task.id

    return {"llm_task_id": task.id}
```

---

## Step 7: Monitor GPU Workers

**Query worker registry** to see GPU workers:

```sql
-- Active GPU workers
SELECT
    worker_id,
    hostname,
    region,
    capabilities->>'gpu_model' AS gpu_model,
    capabilities->>'vram_gb' AS vram_gb,
    last_heartbeat
FROM worker_nodes
WHERE
    status = 'online'
    AND capabilities->>'gpu' = 'true'
ORDER BY last_heartbeat DESC;
```

**Example output:**

```
worker_id        | hostname       | region     | gpu_model   | vram_gb | last_heartbeat
-----------------|----------------|------------|-------------|---------|-------------------
gpu-worker-01    | gpu-server-1   | us-east-1  | Tesla V100  | 16      | 2026-02-17 10:45:32
gpu-worker-02    | gpu-server-2   | us-west-2  | A100        | 40      | 2026-02-17 10:45:30
gpu-worker-03    | gpu-server-1   | us-east-1  | Tesla V100  | 16      | 2026-02-17 10:45:28
```

**Monitor GPU utilization:**

```bash
# On GPU worker server
watch -n 1 nvidia-smi

# Monitor Celery task queue
celery -A rufus.celery_app inspect active
celery -A rufus.celery_app inspect stats
celery -A rufus.celery_app inspect registered | grep gpu
```

---

## Production Deployment

### Docker Compose

**File:** `docker-compose.gpu.yml`

```yaml
version: '3.8'

services:
  # GPU Worker (requires nvidia-docker runtime)
  gpu-worker:
    build:
      context: .
      dockerfile: Dockerfile.gpu
    runtime: nvidia  # CRITICAL: Enable GPU passthrough
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility

      # Worker config
      WORKER_ID: "gpu-worker-${HOSTNAME}"
      WORKER_REGION: "us-east-1"
      WORKER_CAPABILITIES: |
        {
          "gpu": true,
          "gpu_model": "Tesla V100",
          "vram_gb": 16,
          "cuda_version": "12.1",
          "onnx_gpu": true,
          "pytorch": true
        }

      # Database and Celery
      DATABASE_URL: "postgresql://rufus:secret@postgres/rufus"
      CELERY_BROKER_URL: "redis://redis:6379/0"
      CELERY_RESULT_BACKEND: "redis://redis:6379/0"

    command: >
      celery -A rufus.celery_app worker
        --loglevel=info
        --concurrency=2
        --pool=solo
        -Q gpu-inference
        -n gpu-worker-01@%h

    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

    depends_on:
      - postgres
      - redis

  # Standard CPU worker
  cpu-worker:
    build: .
    environment:
      DATABASE_URL: "postgresql://rufus:secret@postgres/rufus"
      CELERY_BROKER_URL: "redis://redis:6379/0"
      CELERY_RESULT_BACKEND: "redis://redis:6379/0"
    command: >
      celery -A rufus.celery_app worker
        --loglevel=info
        --concurrency=10
        -Q default
    deploy:
      replicas: 3

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: rufus
      POSTGRES_USER: rufus
      POSTGRES_PASSWORD: secret

  redis:
    image: redis:7-alpine
```

**Dockerfile.gpu:**

```dockerfile
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# Install Python
RUN apt-get update && apt-get install -y \
    python3.10 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Rufus SDK
WORKDIR /app
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# Install GPU-specific dependencies
RUN pip3 install \
    onnxruntime-gpu==1.18.1 \
    torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 \
    transformers accelerate bitsandbytes

# Copy application code
COPY . .

# Verify GPU access at build time (optional)
RUN python3 -c "import torch; assert torch.cuda.is_available(), 'CUDA not available!'"

CMD ["celery", "-A", "rufus.celery_app", "worker", "--loglevel=info"]
```

**Deploy:**

```bash
# Start GPU worker (requires nvidia-docker runtime)
docker-compose -f docker-compose.gpu.yml up -d

# Verify GPU is accessible
docker-compose -f docker-compose.gpu.yml exec gpu-worker nvidia-smi

# Check worker registration
docker-compose -f docker-compose.gpu.yml exec gpu-worker \
    python3 -c "from rufus.worker_registry import WorkerRegistry; print('Worker registered')"
```

### Kubernetes

**File:** `k8s/gpu-worker-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rufus-gpu-worker
  labels:
    app: rufus-gpu-worker
spec:
  replicas: 2
  selector:
    matchLabels:
      app: rufus-gpu-worker
  template:
    metadata:
      labels:
        app: rufus-gpu-worker
    spec:
      # Schedule on GPU nodes only
      nodeSelector:
        cloud.google.com/gke-accelerator: nvidia-tesla-v100

      containers:
      - name: worker
        image: myregistry/rufus-gpu-worker:latest
        command:
        - celery
        - -A
        - rufus.celery_app
        - worker
        - --loglevel=info
        - --concurrency=2
        - -Q
        - gpu-inference
        - -n
        - gpu-worker@%h

        env:
        - name: WORKER_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: WORKER_REGION
          value: "us-central1"
        - name: WORKER_CAPABILITIES
          value: |
            {
              "gpu": true,
              "gpu_model": "Tesla V100",
              "vram_gb": 16,
              "cuda_version": "12.1"
            }
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: rufus-secrets
              key: database-url
        - name: CELERY_BROKER_URL
          value: "redis://redis-service:6379/0"

        resources:
          limits:
            nvidia.com/gpu: 1  # Request 1 GPU
            memory: "32Gi"
            cpu: "8"
          requests:
            nvidia.com/gpu: 1
            memory: "16Gi"
            cpu: "4"
```

---

## Performance Optimization Tips

1. **Batch Inference**: Process multiple inputs in a single GPU call
   ```python
   # Bad: 10 GPU calls (10ms each = 100ms total)
   for item in items:
       result = model.predict(item)

   # Good: 1 GPU call (15ms total)
   results = model.predict_batch(items)
   ```

2. **Model Quantization**: Use FP16/INT8 for 2-4x speedup
   ```python
   # ONNX Runtime with FP16
   session = ort.InferenceSession(
       "model_fp16.onnx",
       providers=["CUDAExecutionProvider"],
   )

   # PyTorch with FP16
   model = AutoModel.from_pretrained(
       "model",
       torch_dtype=torch.float16,
   )
   ```

3. **TensorRT Optimization**: Convert ONNX to TensorRT for max throughput
   ```bash
   trtexec --onnx=model.onnx --saveEngine=model.trt --fp16
   ```

4. **Worker Concurrency**: Set based on GPU memory
   ```bash
   # 16GB GPU: concurrency=2 (8GB per task)
   # 40GB GPU: concurrency=4 (10GB per task)
   # 80GB GPU: concurrency=8 (10GB per task)
   ```

5. **Pre-load Models**: Load at worker startup, not per-task
   ```python
   @worker_process_init.connect
   def load_models(**kwargs):
       executor = get_inference_executor()
       # Load all models once
       asyncio.run(executor.initialize())
   ```

---

## Cost Analysis

**GPU vs CPU Workers** (AWS pricing, Jan 2026):

| Instance Type | GPU | vCPU | RAM | GPU RAM | $/hour | Inference/sec | $/1M inferences |
|---------------|-----|------|-----|---------|--------|---------------|-----------------|
| c5.2xlarge    | -   | 8    | 16GB| -       | $0.34  | 50            | $1.89           |
| g4dn.xlarge   | T4  | 4    | 16GB| 16GB    | $0.526 | 500           | $0.29           |
| p3.2xlarge    | V100| 8    | 61GB| 16GB    | $3.06  | 2000          | $0.43           |
| p4d.24xlarge  | A100| 96   | 1.1TB| 320GB  | $32.77 | 20000         | $0.46           |

**Conclusion:** GPU workers are **6-10x cheaper per inference** for AI workloads, despite higher hourly cost.

---

## FAQ

**Q: Can I use consumer GPUs (RTX 4090, etc.)?**
A: Yes! Change `WORKER_CAPABILITIES` to reflect your GPU model. Works with any CUDA-compatible GPU.

**Q: How do I route specific models to specific GPUs?**
A: Create multiple queues (e.g., `gpu-small-models`, `gpu-large-models`) and start workers with different queue filters based on GPU capabilities.

**Q: Can I use CPU fallback if GPU workers are busy?**
A: Yes! Set Celery task routes with fallback:
```python
celery_app.conf.task_routes = {
    'my_app.ai_tasks.run_llm_inference': {
        'queue': 'gpu-inference',
        'routing_key': 'gpu-inference',
        'fallback': 'cpu-inference',  # Custom logic needed
    },
}
```

**Q: How do I handle GPU OOM errors?**
A: Use the `fallback_on_error` setting in `AIInferenceConfig` to gracefully handle errors, and set appropriate concurrency limits.

**Q: Can I use multiple GPUs per worker?**
A: Yes! Set `CUDA_VISIBLE_DEVICES=0,1,2,3` and increase `--concurrency`. Use model parallelism for large models.

---

## Summary

You now have a **complete GPU-enabled AI inference system** with Rufus:

✅ Worker capabilities tracking
✅ GPU queue routing
✅ Custom LLM inference provider
✅ Workflow YAML configuration
✅ Docker + Kubernetes deployment
✅ Production monitoring

**Next steps:**
1. Deploy GPU worker with your model
2. Create AI_INFERENCE workflow steps
3. Monitor performance with `nvidia-smi` and Celery Flower
4. Optimize batch sizes and concurrency for your workload
