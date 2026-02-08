# BitNet Integration Research & Plan

## Executive Summary

Microsoft's [BitNet](https://github.com/microsoft/BitNet) is an inference framework for 1-bit (1.58-bit ternary) Large Language Models that runs efficiently on CPUs. This document analyzes how BitNet fits into the Rufus SDK inference pipeline and proposes an integration plan.

**Key finding**: BitNet maps naturally to Rufus's existing `InferenceProvider` interface as a new runtime alongside TFLite and ONNX, with a secondary integration path via the existing HTTP polyglot step type for server-mode deployments.

---

## 1. What is BitNet?

BitNet is Microsoft's inference engine for **1.58-bit quantized LLMs** — models where weights are reduced to ternary values (-1, 0, 1). Built on top of llama.cpp with custom kernels from T-MAC.

### Performance Characteristics

| Platform | Speedup vs FP16 | Energy Reduction |
|----------|-----------------|------------------|
| ARM CPUs | 1.37x – 5.07x | 55–70% |
| x86 CPUs | 2.37x – 6.17x | 72–82% |

- Runs 100B parameter models at **5–7 tokens/sec on a single CPU**
- 2.4B parameter model (BitNet-b1.58-2B-4T) suitable for edge devices
- Models use GGUF format (converted from HuggingFace safetensors)

### Why BitNet Matters for Rufus Edge

1. **CPU-only inference** — no GPU required, matches Rufus's edge device targets (POS, ATMs, kiosks)
2. **Extreme efficiency** — 55–82% energy reduction critical for battery/power-constrained edge devices
3. **Small model footprint** — 1.58-bit quantization means a 2.4B model fits in ~500MB RAM
4. **Text generation** — complements existing classification/anomaly detection (TFLite/ONNX) with generative AI capabilities

---

## 2. Current Rufus Inference Architecture

### Existing Components

```
InferenceProvider (interface)         # src/rufus/providers/inference.py
├── TFLiteInferenceProvider           # src/rufus/implementations/inference/tflite.py
├── ONNXInferenceProvider             # src/rufus/implementations/inference/onnx.py
└── InferenceFactory                  # src/rufus/implementations/inference/factory.py
    └── HardwareIdentity              # Auto-detects CUDA, CoreML, EdgeTPU, CPU

AIInferenceConfig (model)             # src/rufus/models.py:120
AIInferenceWorkflowStep               # src/rufus/models.py:202
InferenceExecutor                     # src/rufus_edge/inference_executor.py

InferenceRuntime enum:
  - TFLITE
  - ONNX
  - CUSTOM
```

### Execution Pipeline

```
Workflow YAML (type: "AI_INFERENCE")
    ↓
WorkflowBuilder → AIInferenceWorkflowStep
    ↓
InferenceExecutor.execute_inference()
    ├── Extract input from state (dot-notation path)
    ├── Preprocess (normalize, resize, flatten, expand_dims)
    ├── Load model via InferenceProvider (cached)
    ├── Run inference (with timeout)
    ├── Postprocess (softmax, threshold, argmax, binary)
    └── Merge result into workflow state
```

### Current Gap

`AIInferenceWorkflowStep` is fully modeled in `models.py` and the `InferenceExecutor` pipeline is complete, but **`Workflow.next_step()` in `workflow.py` does not yet handle `AI_INFERENCE` step type**. This is a pre-existing gap independent of BitNet.

### Nature of Existing Providers

| Provider | Input | Output | Use Case |
|----------|-------|--------|----------|
| TFLite | Tensor (numpy array) | Tensor (numpy array) | Classification, anomaly detection, small models |
| ONNX | Tensor (numpy array) | Tensor (numpy array) | Same + cross-framework model support |

Both are **tensor-in, tensor-out** systems designed for fixed-shape ML models (CNNs, tabular models, etc.).

### Nature of BitNet

| Aspect | BitNet | TFLite/ONNX |
|--------|--------|-------------|
| Input | Text prompt (string) | Numeric tensors |
| Output | Generated text (string/tokens) | Numeric tensors |
| Model type | Autoregressive LLM | Fixed-function ML |
| Execution | Iterative token generation | Single forward pass |
| Latency | 100ms–10s+ (varies with token count) | 1–50ms typical |
| Memory | 500MB–10GB+ | 1–100MB typical |
| Format | GGUF | .tflite / .onnx |

This is a **fundamentally different inference modality** — generative text vs. tensor classification.

---

## 3. Integration Options

### Option A: Native InferenceProvider (Recommended for Edge)

Add `BitNetInferenceProvider` as a new `InferenceProvider` implementation.

**Architecture:**

```
InferenceProvider (interface)
├── TFLiteInferenceProvider
├── ONNXInferenceProvider
└── BitNetInferenceProvider (NEW)
    ├── Wraps bitnet.cpp subprocess or C FFI
    ├── Model loading via GGUF files
    ├── Text-in/text-out interface
    └── Adapts to tensor-based InferenceResult
```

**Implementation approach:**

```python
class BitNetInferenceProvider(InferenceProvider):
    """
    Inference provider for BitNet 1-bit LLMs.

    Wraps the bitnet.cpp inference engine for on-device
    text generation on CPU-only edge devices.
    """

    runtime = InferenceRuntime.BITNET  # New enum value

    async def load_model(self, model_path, model_name, **kwargs):
        # Load GGUF model via bitnet.cpp subprocess or ctypes
        # Configure: context_size, threads, temperature
        pass

    async def run_inference(self, model_name, inputs, **kwargs):
        # inputs: {"prompt": "Analyze this transaction...", "max_tokens": 256}
        # Returns: InferenceResult with {"text": "...", "tokens": [...]}
        pass
```

**Pros:**
- Fits the existing provider pattern
- Works offline (critical for edge)
- Managed by InferenceFactory hardware detection
- Lifecycle managed by InferenceExecutor
- Model caching works as-is

**Cons:**
- InferenceProvider interface is tensor-oriented (needs adaptation for text I/O)
- BitNet's subprocess model may need careful resource management
- GGUF model loading is different from TFLite/ONNX patterns

**Required changes:**
1. Add `BITNET = "bitnet"` to `InferenceRuntime` enum
2. Implement `BitNetInferenceProvider` in `src/rufus/implementations/inference/bitnet.py`
3. Update `InferenceFactory` to detect CPU capabilities (AVX2, ARM NEON) and offer BitNet
4. Extend `AIInferenceConfig` preprocessing to support text prompting (template rendering)
5. Add text-oriented postprocessing (parse JSON from LLM output, extract fields)
6. Wire `AI_INFERENCE` step handling in `Workflow.next_step()`

### Option B: HTTP Polyglot Step (Recommended for Server/Hybrid)

Use BitNet's `run_inference_server.py` which starts a llama.cpp-compatible HTTP server, then call it via existing `HTTP` step type.

**Architecture:**

```
Edge Device                           BitNet Server (local or network)
┌─────────────────┐                  ┌─────────────────────┐
│ Rufus Workflow   │   HTTP/REST     │ llama-server         │
│  HTTP Step       │ ───────────────>│  (BitNet GGUF model) │
│  type: "HTTP"    │                 │  Port 8080           │
│  POST /completion│ <───────────────│  /completion          │
└─────────────────┘   JSON response  └─────────────────────┘
```

**YAML configuration:**

```yaml
- name: "Analyze_Transaction"
  type: "HTTP"
  http_config:
    method: "POST"
    url: "http://localhost:8080/completion"
    headers:
      Content-Type: "application/json"
    body:
      prompt: "Analyze this transaction for fraud: amount={{state.amount}}, merchant={{state.merchant}}, location={{state.location}}. Respond with JSON: {\"risk_score\": float, \"reason\": string}"
      n_predict: 256
      temperature: 0.2
    timeout: 30
  output_key: "llm_analysis"
  automate_next: true
```

**Pros:**
- Zero code changes to Rufus SDK — works today
- llama.cpp server is battle-tested
- API is OpenAI-compatible (portable)
- Can run BitNet server on separate hardware
- Easy to swap models without code changes

**Cons:**
- Requires network connectivity (breaks offline-first principle)
- Additional process to manage (server lifecycle)
- Higher latency (HTTP overhead)
- Not integrated with InferenceFactory/HardwareIdentity

### Option C: Hybrid Approach (Recommended Overall)

Combine both: native provider for offline edge, HTTP for server deployments.

```
Configuration determines mode:

runtime: "bitnet"          → Native BitNetInferenceProvider (offline)
runtime: "bitnet-server"   → HTTP step to local/remote llama-server
```

The `InferenceFactory` selects based on:
- Device capabilities (RAM, CPU features)
- Deployment mode (edge standalone vs. connected)
- Model size (2B native, larger models via server)

---

## 4. Proposed Integration Plan

### Phase 1: HTTP Server Integration (Low effort, immediate value)

No SDK changes required. Document how to:
1. Deploy BitNet server alongside edge devices
2. Configure HTTP workflow steps to call `/completion` endpoint
3. Template prompts with Jinja2 using workflow state
4. Parse LLM JSON responses in subsequent DECISION steps

**Deliverables:**
- Example workflow YAML with BitNet HTTP steps
- Docker Compose for BitNet server + Rufus edge agent
- Documentation in USAGE_GUIDE.md

### Phase 2: Native Provider Implementation

**Step 2a: Core Provider**
- Add `InferenceRuntime.BITNET` enum value (`src/rufus/providers/inference.py`)
- Implement `BitNetInferenceProvider` (`src/rufus/implementations/inference/bitnet.py`)
  - Subprocess wrapper around `bitnet.cpp` binary
  - GGUF model loading and lifecycle
  - Text prompt → text response interface
  - Configurable: threads, context size, temperature, max tokens

**Step 2b: Text I/O Adaptation**
- Extend `AIInferenceConfig` with LLM-specific fields:
  - `prompt_template: str` — Jinja2 template for constructing prompts from state
  - `max_tokens: int` — Maximum generation length
  - `temperature: float` — Sampling temperature
  - `response_format: str` — "text", "json", "structured"
  - `response_schema: Optional[Dict]` — Expected JSON schema for validation
- Add `TextPreprocessor` (renders prompt template from state)
- Add `LLMPostprocessor` (parses text/JSON output, extracts structured fields)

**Step 2c: Factory Integration**
- Update `InferenceFactory` to detect BitNet-compatible hardware:
  - x86_64 with AVX2 support
  - ARM64 (Apple Silicon, Raspberry Pi 5, etc.)
  - Sufficient RAM for model size
- Add `HardwareIdentity` fields for LLM capability
- Add `ProviderPreference.BITNET` option

**Step 2d: Wire AI_INFERENCE in Workflow** (pre-existing gap)
- Add `AIInferenceWorkflowStep` handling in `Workflow.next_step()`
- This unblocks all inference providers, not just BitNet

### Phase 3: Advanced Features

- **Model management via Cloud Control Plane**: Push GGUF models to edge devices via ETag-based config (like fraud rule updates)
- **Prompt versioning**: Snapshot prompt templates alongside workflow definitions
- **Streaming support**: Token-by-token output for real-time UX on kiosk displays
- **Multi-model pipelines**: Chain BitNet (text) → TFLite (classification) in a single workflow
- **Conversation state**: Maintain chat history across workflow steps for multi-turn interactions

---

## 5. Fintech Use Cases

### 5.1 Transaction Fraud Narrative

```yaml
steps:
  - name: "Score_Transaction"
    type: "AI_INFERENCE"
    ai_config:
      model_name: "fraud_classifier"
      runtime: "tflite"
      input_source: "state.transaction_features"
      postprocessing: "threshold"
      postprocessing_params:
        threshold: 0.7
      output_key: "fraud_score"
    automate_next: true

  - name: "Generate_Fraud_Explanation"
    type: "AI_INFERENCE"
    ai_config:
      model_name: "bitnet_2b"
      runtime: "bitnet"
      prompt_template: |
        Transaction flagged with risk score {{ state.fraud_score.confidence }}.
        Details: amount={{ state.amount }}, merchant={{ state.merchant }}.
        Explain why this may be fraudulent in 2-3 sentences.
      max_tokens: 128
      temperature: 0.1
      output_key: "fraud_explanation"
    automate_next: true
```

### 5.2 Offline Customer Support (Kiosk)

On-device LLM for customer queries when network is down:

```yaml
- name: "Answer_Customer_Query"
  type: "AI_INFERENCE"
  ai_config:
    model_name: "bitnet_2b"
    runtime: "bitnet"
    prompt_template: |
      You are a banking kiosk assistant. Answer concisely.
      Customer question: {{ state.customer_query }}
    max_tokens: 256
    temperature: 0.3
    output_key: "assistant_response"
    fallback_on_error: "default"
    default_result:
      text: "I'm unable to answer right now. Please visit a teller."
```

### 5.3 Receipt/Document Summarization

```yaml
- name: "Summarize_Receipt"
  type: "AI_INFERENCE"
  ai_config:
    model_name: "bitnet_2b"
    runtime: "bitnet"
    prompt_template: |
      Summarize this receipt in JSON format:
      {{ state.ocr_text }}
      Format: {"merchant": str, "total": float, "items": [str], "date": str}
    max_tokens: 256
    temperature: 0.0
    response_format: "json"
    output_key: "receipt_summary"
```

---

## 6. Technical Considerations

### 6.1 Resource Constraints

| Model | Parameters | GGUF Size (est.) | RAM Required | Suitable Devices |
|-------|-----------|-------------------|--------------|------------------|
| BitNet-b1.58-2B-4T | 2.4B | ~400MB | ~1GB | Modern POS, Kiosks, RPi5 |
| bitnet_b1_58-3B | 3.3B | ~550MB | ~1.5GB | Mid-range kiosks, ATMs |
| Llama3-8B-1.58 | 8B | ~1.3GB | ~3GB | High-end ATMs, servers |
| Falcon3-10B-1.58 | 10B | ~1.6GB | ~4GB | Edge servers only |

For Rufus Edge devices (POS terminals, mobile readers): the **2.4B model** is the primary target.

### 6.2 Latency Budget

Typical edge workflow latency budgets:

| Operation | Budget | BitNet 2B (est.) |
|-----------|--------|-------------------|
| Payment authorization | 100–500ms | Too slow for prompt path |
| Fraud explanation (async) | 2–10s | ~128 tokens @ ~20 tok/s = 6s |
| Customer query | 5–30s | ~256 tokens @ ~20 tok/s = 12s |
| Document summary | 10–60s | ~256 tokens @ ~20 tok/s = 12s |

BitNet inference should be modeled as **async steps** (not blocking the payment flow).

### 6.3 Subprocess vs. C FFI

| Approach | Pros | Cons |
|----------|------|------|
| **Subprocess** (recommended initially) | Simple, isolated, crash-safe | IPC overhead, startup time |
| **C FFI** (ctypes/cffi) | Lower latency, no IPC | Complex, crashes propagate |
| **Python bindings** (future) | Clean API | Doesn't exist yet for BitNet |

Recommendation: Start with subprocess, consider FFI for v2 if latency is critical.

### 6.4 Model Lifecycle

Integration with existing Rufus model management:

```
Cloud Control Plane
    ├── Model Registry (GGUF files)
    ├── ETag-based model push (same as config push)
    └── Device capability matching (HardwareIdentity)

Edge Device
    ├── Model download on sync
    ├── InferenceProvider.load_model()
    ├── Model version tracking (AIInferenceConfig.model_version)
    └── Automatic model cache management
```

### 6.5 Security Considerations

- **Prompt injection**: Edge LLMs could be manipulated via crafted transaction data injected into prompts. Must sanitize state values before template rendering.
- **Output validation**: LLM outputs are non-deterministic. Never use raw LLM output for financial decisions — always gate through deterministic logic (DECISION steps with hard thresholds).
- **Model integrity**: GGUF files pushed from cloud must be signature-verified.
- **PCI-DSS**: No cardholder data should appear in prompts or model outputs. Sanitize before inference.

---

## 7. Comparison with Alternatives

| Framework | Quantization | Platform | Inference Speed | Edge Suitability |
|-----------|-------------|----------|-----------------|------------------|
| **BitNet** | 1.58-bit ternary | CPU (ARM, x86) | 5–20 tok/s (CPU) | Excellent |
| llama.cpp (GGML) | 2-8 bit | CPU + GPU | 10–50 tok/s | Good |
| ONNX GenAI | FP16/INT8 | CPU + GPU | 15–40 tok/s | Moderate |
| TFLite (Gemma) | INT8 | Mobile/Edge | 5–15 tok/s | Good for Android |
| MLC-LLM | Mixed | Wide | 10–30 tok/s | Good |

BitNet's advantage is **extreme efficiency on CPU** — no GPU required, lowest energy consumption, smallest model footprint. This aligns directly with Rufus Edge's target of power-constrained fintech devices.

---

## 8. Recommended Priority

1. **Wire `AI_INFERENCE` in `Workflow.next_step()`** — Unblocks all inference providers (pre-existing gap, independent of BitNet)
2. **Document HTTP polyglot pattern** for BitNet server — Immediate value, zero code changes
3. **Implement `BitNetInferenceProvider`** — Native edge integration
4. **Extend `AIInferenceConfig`** for text generation parameters
5. **Update `InferenceFactory`** for BitNet hardware detection
6. **Cloud model push** for GGUF files via existing ETag sync

---

## 9. Open Questions

1. **Python bindings**: Will Microsoft release official Python bindings for bitnet.cpp? This would simplify the provider significantly.
2. **Model fine-tuning**: Can BitNet models be fine-tuned for domain-specific fintech vocabulary? (Currently unclear from public docs.)
3. **Structured output**: How reliable is JSON-mode output from 2B parameter models? May need constrained decoding.
4. **Warm-up time**: How long does initial GGUF model loading take? Impacts edge device boot time.
5. **Concurrent requests**: Can a single bitnet.cpp process handle multiple inference requests? (llama.cpp supports continuous batching.)
