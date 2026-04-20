# Edge Device Package Footprint

Complete reference for installed package size across all edge deployment scenarios.

---

## What Ships in Each Wheel (v0.6.0+)

As of v0.6.0, Ruvon ships as **three separate wheels**. Edge devices install only `ruvon-edge`,
which pulls in `ruvon-sdk` (core) but never installs the 10 MB cloud control plane.

```
ruvon_sdk-0.6.0-py3-none-any.whl  (~2.5 MB)
│
├── ruvon/                          1.9 MB  57 files  — Core SDK + all implementations
│   ├── workflow.py                 (970 lines) — Workflow orchestrator
│   ├── builder.py                  (554 lines) — YAML loader + importlib resolver
│   ├── models.py                   (287 lines) — Pydantic step/workflow models
│   ├── tasks.py                    (827 lines) — Celery task definitions (cloud only)
│   ├── celery_app.py               (301 lines) — Celery init (cloud only)
│   ├── heartbeat.py / zombie_scanner.py        — Worker monitoring (cloud only)
│   ├── providers/                  (7 files)   — Protocol interfaces
│   └── implementations/            716 KB      — All provider implementations
│       ├── persistence/  sqlite.py, postgres.py, memory.py, redis.py (stub)
│       ├── execution/    sync.py, celery.py, thread_pool.py
│       ├── inference/    factory.py, onnx.py, tflite.py
│       ├── security/     crypto_utils.py, secrets_provider.py, semantic_firewall.py
│       ├── observability/ logging.py, events.py, noop.py
│       ├── templating/   jinja2.py
│       └── expression_evaluator/ simple.py
│
└── ruvon_cli/                      520 KB  12 files  — CLI tool

ruvon_sdk_edge-0.6.0-py3-none-any.whl  (~250 KB)
│
└── ruvon_edge/                     232 KB  8 files   — Edge agent
    ├── agent.py                    (465 lines) — RuvonEdgeAgent main class
    ├── config_manager.py           (787 lines) — ETag-based config polling
    ├── sync_manager.py             (430 lines) — Store-and-Forward queuing
    ├── models.py                   (294 lines) — PaymentState, SAFTransaction
    ├── inference_executor.py       (390 lines) — On-device AI orchestration
    ├── delta_updates.py            (379 lines) — Config diff/patch logic
    └── payment_steps.py            (212 lines) — Reference payment step functions

ruvon_sdk_server-0.6.0-py3-none-any.whl  (~10 MB)
│
└── ruvon_server/                   10 MB   42 files  — Cloud control plane
```

### What is and is not included in each wheel

| Item | `ruvon-sdk` | `ruvon-edge` | `ruvon-server` |
|------|:-----------:|:----------------:|:-----------------:|
| `ruvon/implementations/` | Yes | via dependency | via dependency |
| `ruvon_cli/` | Yes | No | No |
| `ruvon_edge/` | No | Yes | No |
| `ruvon_server/` | No | No | Yes |
| `ruvon/examples/` | **No** | **No** | **No** |
| User-written step functions | **No** | **No** | **No** |

> **User step functions are not part of the package footprint.**
> If your steps import `scikit-learn`, `tensorflow`, `requests`, or any other library,
> those add to your on-device footprint on top of these numbers.

---

## Core Dependencies (always installed)

These 17 packages install with any `pip install ruvon-sdk`:

| Package | Purpose | Approx size |
|---------|---------|-------------|
| `pydantic>=2.0` | State model validation | ~3 MB |
| `PyYAML>=6.0` | Workflow YAML parsing | ~1 MB |
| `jinja2>=3.1` | Template rendering | ~1 MB |
| `aiosqlite>=0.19` | Async SQLite for edge | ~0.3 MB |
| `httpx>=0.25` | HTTP steps + config polling | ~2 MB |
| `cryptography>=41.0` | Encryption (PCI-DSS) | ~4 MB |
| `sqlalchemy>=2.0` | Schema definition | ~3 MB |
| `alembic>=1.13` | Database migrations | ~1 MB |
| `orjson>=3.9` | Fast JSON serialization | ~0.5 MB |
| `croniter>=2.0` | CRON_SCHEDULE steps | ~0.2 MB |
| `jsonschema>=4.17` | JSON validation | ~0.5 MB |
| `typer + click` | CLI framework | ~1 MB |
| `anyio>=4.0` | Async abstraction | ~0.5 MB |
| `python-dotenv>=1.0` | Env variable loading | ~0.1 MB |
| `typing-extensions` | Type hint backports | ~0.1 MB |
| **Total** | | **~15–20 MB** |

---

## Optional Extras

### `ruvon-sdk` extras

Install with `pip install 'ruvon-sdk[extra1,extra2]'`:

| Extra | Packages added | Added size | Use on edge? |
|-------|---------------|------------|--------------|
| `[postgres]` | `asyncpg` | +2 MB | Cloud only |
| `[performance]` | `uvloop` | +2 MB | Yes — 2–4× faster async I/O |
| `[cli]` | `rich` | +2 MB | Optional — richer terminal output |

### `ruvon-edge` extras

Install with `pip install 'ruvon-edge[edge]'`:

| Extra | Packages added | Added size | Use on edge? |
|-------|---------------|------------|--------------|
| `[edge]` | `websockets`, `psutil`, `numpy` | +14 MB | Yes — WebSocket commands, health metrics |

### `ruvon-server` extras

Install with `pip install 'ruvon-server[server,celery,auth]'`:

| Extra | Packages added | Added size | Use on edge? |
|-------|---------------|------------|--------------|
| `[server]` | `fastapi`, `uvicorn`, `starlette`, `slowapi` | +10 MB | Cloud only |
| `[celery]` | `celery`, `redis`, `psycopg2-binary`, `prometheus-client` | +10 MB | Cloud only |
| `[auth]` | `python-jose` | +1 MB | Cloud only |
| `[all]` | All server extras above | +21 MB | Cloud only |

> **`redis` and `celery` persistence/execution providers raise `ValueError` in the CLI
> and are not usable on edge devices. Use `sqlite` + `sync` or `thread_pool`.**

---

## Installed Footprint by Scenario

### Scenario A — Minimal (offline payment, no AI, no monitoring)

```bash
pip install ruvon-edge
```

| Layer | Size |
|-------|------|
| `ruvon-sdk` wheel (core + CLI) | ~2.5 MB |
| `ruvon-edge` wheel (edge agent) | ~250 KB |
| Core dependencies | ~15–20 MB |
| **Total on disk** | **~15–20 MB** |

**Capabilities:** STANDARD/DECISION/LOOP/HITL steps, SAF queue, SQLite persistence, ETag config polling.

**Minimum device:** 128 MB RAM, 64 MB free storage, Python 3.9+.

---

### Scenario B — Edge with system monitoring and WebSocket commands

```bash
pip install 'ruvon-edge[edge]'
```

| Layer | Size |
|-------|------|
| Scenario A | ~15–20 MB |
| `websockets` | +2 MB |
| `psutil` | +2 MB |
| `numpy` (required by psutil + inference) | +10 MB |
| **Total on disk** | **~30–35 MB** |

**Capabilities:** Everything above + WebSocket device command channel, CPU/memory/disk health metrics, prepared for on-device inference.

**Minimum device:** 128 MB RAM, 100 MB free storage.

---

### Scenario C — Edge with ONNX inference (fraud detection, risk scoring)

```bash
pip install 'ruvon-edge[edge]'
pip install onnxruntime>=1.16.0
# Download model files separately
```

| Layer | Size |
|-------|------|
| Scenario B | ~30–35 MB |
| `onnxruntime` | +50–80 MB |
| Model files (fraud scoring, anomaly detection, etc.) | +10–500 MB |
| **Total on disk** | **~100–600 MB** |

**Capabilities:** Everything above + `InferenceExecutorFactory` → on-device risk scoring, floor-limit ML decisions, anomaly detection.

**Minimum device:** 256 MB RAM, 200 MB+ free storage.

---

### Scenario D — Edge with TensorFlow Lite

```bash
pip install 'ruvon-edge[edge]'
pip install tflite-runtime
```

| Layer | Size |
|-------|------|
| Scenario B | ~30–35 MB |
| `tflite-runtime` (stripped runtime, not full TF) | +10 MB |
| Model files | +10–200 MB |
| **Total on disk** | **~60–250 MB** |

Preferred over full TensorFlow on constrained devices. Full TF is ~700 MB installed.

**Minimum device:** 256 MB RAM, 100–300 MB free storage.

---

### Scenario E — Full cloud deployment (reference)

```bash
pip install 'ruvon-sdk[postgres,performance,cli]'
pip install 'ruvon-server[all]'
```

| Layer | Size |
|-------|------|
| Core + server extras combined | ~35–45 MB |
| Docker container (`python:3.11-slim` base) | ~220–230 MB |

---

## Runtime Memory (RSS)

Resident set size while the process is running — distinct from disk footprint.

| Scenario | Python runtime | Ruvon + deps | Models loaded | RSS |
|----------|---------------|--------------|---------------|-----|
| Minimal, no AI | 30 MB | 20 MB | — | **~50 MB** |
| With `[edge]` | 30 MB | 35 MB | — | **~65 MB** |
| With ONNX | 30 MB | 35 MB | 50–100 MB | **~115–165 MB** |
| With TFLite | 30 MB | 35 MB | 20–50 MB | **~85–115 MB** |

---

## What `ruvon_edge` Actually Imports from Core

Only a subset of the 57-file `ruvon/` package is imported by the edge agent.
The rest is on disk but never loaded into memory.

**Imported at runtime (edge):**

```
ruvon.workflow                          ← Workflow orchestrator
ruvon.builder                           ← YAML loader
ruvon.models                            ← StepContext, directives
ruvon.providers.*                       ← Protocol interfaces (7 files)
ruvon.implementations.persistence.sqlite
ruvon.implementations.execution.sync
ruvon.implementations.observability.logging
ruvon.implementations.templating.jinja2
ruvon.implementations.expression_evaluator.simple
ruvon.implementations.security.crypto_utils
ruvon.implementations.inference.*       ← Only if AI inference enabled
```

**Never imported on edge (on disk but not loaded):**

| Module | Purpose |
|--------|---------|
| `ruvon.celery_app` | Celery initialization (cloud workers only) |
| `ruvon.tasks` | Celery task definitions (cloud workers only) |
| `ruvon.worker_registry` | Celery fleet tracking (cloud only) |
| `ruvon.zombie_scanner` | Zombie workflow detection (monitoring only) |
| `ruvon.heartbeat` | Worker heartbeat (cloud workers only) |
| `ruvon.engine` | Legacy WorkflowEngine (deprecated) |
| `ruvon.implementations.execution.celery` | Celery executor (cloud only) |
| `ruvon.implementations.execution.thread_pool` | Thread-based parallel (optional) |
| `ruvon.implementations.persistence.postgres` | PostgreSQL (cloud only) |
| `ruvon.implementations.persistence.redis` | Redis stub (not implemented) |
| `ruvon_cli.*` | CLI tool (cloud/dev only) |
| `ruvon_server.*` | REST API server (cloud only) |

---

## Device Hardware Requirements

| Scenario | Min RAM | Min Storage | Python | Typical hardware |
|----------|---------|-------------|--------|-----------------|
| Minimal (no AI) | 128 MB | 64 MB | 3.9+ | Basic POS, simple kiosk |
| With `[edge]` | 128 MB | 100 MB | 3.9+ | ATM, mobile reader |
| With ONNX | 256 MB | 200 MB+ | 3.9+ | Smart POS, fraud scoring terminal |
| With TFLite | 256 MB | 100–300 MB | 3.9+ | Mobile reader, advanced kiosk |

---

## Reducing Footprint

As of v0.6.0, `pip install ruvon-edge` installs only the core engine and edge agent —
the CLI and cloud control plane are in separate wheels and are not installed.

**For severely flash-constrained hardware (<64 MB storage):**

Option 1 — Install only the edge package (no CLI):
```bash
pip install ruvon-edge  # Only ruvon + ruvon_edge, no ruvon_cli or ruvon_server
```

Option 2 — Install from source in editable mode:
```bash
git clone https://github.com/KamikaziD/ruvon-sdk
cd ruvon-sdk
pip install -e packages/ruvon-edge
```

Option 3 — Use a virtual environment with stripped system Python for embedded builds.

---

## Version History

| Version | `ruvon-sdk` size | `ruvon-edge` size | `ruvon-server` size | Notes |
|---------|:----------------:|:---------------------:|:-----------------------:|-------|
| 0.6.0 | ~2.5 MB | ~250 KB | ~10 MB | Package split — edge devices no longer ship cloud code |
| 0.5.4 | 9.3 MB (monolithic) | — | — | JavaScript step type removed |
| 0.5.3 | ~9.3 MB (monolithic) | — | — | Added PARALLEL batch_size |
| 0.5.0 | ~9.1 MB (monolithic) | — | — | Schema consolidation |
