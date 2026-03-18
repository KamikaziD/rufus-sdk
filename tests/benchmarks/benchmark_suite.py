"""
Rufus SDK — Comprehensive Benchmark Suite
==========================================

Covers 11 sections:
  1. JSON Serialization
  2. Import Caching
  3. SQLite Persistence
  4. E2E Workflow
  5. Async Event Loop
  6. Pydantic State Model
  7. Fernet Encryption       (requires cryptography)
  8. HMAC-SHA256
  9. Ed25519 Signatures      (requires cryptography)
 10. API Key Hashing
 11. Full SAF Pipeline       (requires cryptography)

Usage:
    python tests/benchmarks/benchmark_suite.py            # full suite (~60 s)
    python tests/benchmarks/benchmark_suite.py --quick    # ~8 s
    python tests/benchmarks/benchmark_suite.py --output json
    python tests/benchmarks/benchmark_suite.py --no-security
"""

import argparse
import asyncio
import concurrent.futures
import hashlib
import hmac as _hmac
import json
import os
import secrets
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure the project root is on sys.path so importlib can resolve
# `tests.benchmarks.benchmark_suite.*` as dotted paths when running directly.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Optional dependency probes
# ---------------------------------------------------------------------------

try:
    import orjson
    _ORJSON_AVAILABLE = True
except ImportError:
    _ORJSON_AVAILABLE = False

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

try:
    import uvloop
    _UVLOOP_AVAILABLE = True
except ImportError:
    _UVLOOP_AVAILABLE = False

# ---------------------------------------------------------------------------
# Module-level state — must be importable as dotted paths for WorkflowBuilder
# ---------------------------------------------------------------------------

class BenchmarkState(BaseModel):
    counter: int = 0
    payload: str = ""
    result: Optional[str] = None


def bench_step_noop(state: BenchmarkState, context: Any, **kwargs) -> dict:
    return {"counter": state.counter + 1}


def bench_step_heavy(state: BenchmarkState, context: Any, **kwargs) -> dict:
    total = sum(range(100))
    return {"counter": state.counter + 1, "result": str(total)}


# ---------------------------------------------------------------------------
# Inline YAML definition for E2E workflow benchmark (no files on disk)
# ---------------------------------------------------------------------------

BENCH_YAML = """
workflow_type: BenchmarkWorkflow
initial_state_model_path: tests.benchmarks.benchmark_suite.BenchmarkState
steps:
  - name: StepA
    type: STANDARD
    function: tests.benchmarks.benchmark_suite.bench_step_noop
    automate_next: true
  - name: StepB
    type: STANDARD
    function: tests.benchmarks.benchmark_suite.bench_step_heavy
"""

# ---------------------------------------------------------------------------
# Results helpers
# ---------------------------------------------------------------------------

class Section:
    def __init__(self, name: str):
        self.name = name
        self.rows: List[Dict[str, Any]] = []
        self.notes: List[str] = []

    def add(self, label: str, **metrics):
        self.rows.append({"label": label, **metrics})

    def note(self, msg: str):
        self.notes.append(msg)


def _pct(data: List[float], p: float) -> float:
    s = sorted(data)
    idx = int(len(s) * p)
    return s[min(idx, len(s) - 1)]


def _stats(times: List[float]) -> Dict[str, float]:
    total = sum(times)
    return {
        "mean_ms": statistics.mean(times) * 1000,
        "p50_ms": statistics.median(times) * 1000,
        "p95_ms": _pct(times, 0.95) * 1000,
        "ops_per_sec": len(times) / total if total > 0 else 0,
    }


def _print_section(sec: Section):
    WIDTH = 78
    print(f"\n{'=' * WIDTH}")
    print(f"  {sec.name}")
    print(f"{'=' * WIDTH}")
    for row in sec.rows:
        label = row["label"]
        rest = {k: v for k, v in row.items() if k != "label"}
        parts = []
        for k, v in rest.items():
            if isinstance(v, float):
                # Use enough decimal places to show sub-millisecond p95 values
                if (k.endswith("_ms") or k == "ms") and v < 0.01:
                    fmt = f"{v:.4f}"
                elif (k.endswith("_ms") or k == "ms") and v < 0.1:
                    fmt = f"{v:.3f}"
                else:
                    fmt = f"{v:,.2f}"
                parts.append(f"{k}={fmt}")
            else:
                parts.append(f"{k}={v}")
        print(f"  {label:<35} {', '.join(parts)}")
    for note in sec.notes:
        print(f"  NOTE: {note}")


# ---------------------------------------------------------------------------
# Section 1 — JSON Serialization
# ---------------------------------------------------------------------------

def bench_json_serialization(n: int) -> Section:
    sec = Section("1. JSON Serialization")

    payload = {
        "workflow_id": "wf_bench_" + "x" * 20,
        "state": {
            "amount_cents": 99999,
            "currency": "USD",
            "merchant": "Acme Corp",
            "tags": ["fraud", "high-value"],
            "metadata": {"ts": "2026-01-01T00:00:00Z", "region": "us-east-1"},
        },
        "steps": [{"name": f"step_{i}", "type": "STANDARD"} for i in range(10)],
    }
    raw = json.dumps(payload).encode()
    assert len(raw) > 200, "payload too small"

    # Stdlib json
    for _ in range(200):  # warmup
        json.dumps(payload)
    times_enc = []
    for _ in range(n):
        t = time.perf_counter()
        json.dumps(payload)
        times_enc.append(time.perf_counter() - t)

    json_s = json.dumps(payload)
    times_dec = []
    for _ in range(n):
        t = time.perf_counter()
        json.loads(json_s)
        times_dec.append(time.perf_counter() - t)

    st = _stats(times_enc)
    sec.add("stdlib encode 1KB", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])
    st = _stats(times_dec)
    sec.add("stdlib decode 1KB", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    if _ORJSON_AVAILABLE:
        for _ in range(200):
            orjson.dumps(payload)
        times_oj_enc = []
        for _ in range(n):
            t = time.perf_counter()
            orjson.dumps(payload)
            times_oj_enc.append(time.perf_counter() - t)

        oj_bytes = orjson.dumps(payload)
        times_oj_dec = []
        for _ in range(n):
            t = time.perf_counter()
            orjson.loads(oj_bytes)
            times_oj_dec.append(time.perf_counter() - t)

        stdlib_enc_ops = _stats(times_enc)["ops_per_sec"]
        orjson_enc_ops = _stats(times_oj_enc)["ops_per_sec"]
        ratio = orjson_enc_ops / stdlib_enc_ops if stdlib_enc_ops else 0

        st = _stats(times_oj_enc)
        sec.add("orjson encode 1KB", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"],
                speedup=f"{ratio:.1f}x")
        st = _stats(times_oj_dec)
        stdlib_dec_ops = _stats(times_dec)["ops_per_sec"]
        orjson_dec_ops = st["ops_per_sec"]
        ratio_dec = orjson_dec_ops / stdlib_dec_ops if stdlib_dec_ops else 0
        sec.add("orjson decode 1KB", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"],
                speedup=f"{ratio_dec:.1f}x")
    else:
        sec.note("orjson not installed — skipping orjson rows")

    return sec


# ---------------------------------------------------------------------------
# Section 2 — Import Caching
# ---------------------------------------------------------------------------

def bench_import_caching(n: int) -> Section:
    sec = Section("2. Import Caching")

    from rufus.builder import WorkflowBuilder

    paths = [
        "rufus.utils.serialization.serialize",
        "rufus.utils.serialization.deserialize",
        "rufus.builder.WorkflowBuilder",
        "rufus.implementations.persistence.memory.InMemoryPersistence",
        "rufus.implementations.execution.sync.SyncExecutor",
    ]

    # NOTE: intentional use of private API for caching benchmark
    WorkflowBuilder._import_cache.clear()

    cold_times = []
    for p in paths:
        t = time.perf_counter()
        # NOTE: intentional use of private API for caching benchmark
        WorkflowBuilder._import_from_string(p)
        cold_times.append(time.perf_counter() - t)

    warm_times = []
    for _ in range(n):
        for p in paths:
            t = time.perf_counter()
            # NOTE: intentional use of private API for caching benchmark
            WorkflowBuilder._import_from_string(p)
            warm_times.append(time.perf_counter() - t)

    cold_mean = statistics.mean(cold_times) * 1000
    warm_mean = statistics.mean(warm_times) * 1000
    speedup = cold_mean / warm_mean if warm_mean > 0 else 0

    sec.add("cold miss (5 paths)", mean_ms=cold_mean)
    sec.add("warm hit (5 paths)", mean_ms=warm_mean, speedup=f"{speedup:.0f}x")
    # NOTE: intentional use of private API for caching benchmark
    sec.add("cache entries", count=len(WorkflowBuilder._import_cache))
    return sec


# ---------------------------------------------------------------------------
# Section 3 — SQLite Persistence
# ---------------------------------------------------------------------------

async def bench_sqlite(n: int) -> Section:
    sec = Section("3. SQLite Persistence (in-memory)")

    from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

    provider = SQLitePersistenceProvider(db_path=":memory:")
    await provider.initialize()

    # save_workflow
    wf_ids = [str(uuid.uuid4()) for _ in range(n)]
    times_save = []
    for i, wid in enumerate(wf_ids):
        data = {
            "id": wid,
            "workflow_type": "BenchmarkWorkflow",
            "workflow_version": "v1",
            "current_step": "StepA",
            "status": "ACTIVE",
            "state": {"counter": i},
            "definition_snapshot": None,
            "steps_config": [],
            "state_model_path": "tests.benchmarks.benchmark_suite.BenchmarkState",
            "saga_mode": False,
            "completed_steps_stack": [],
            "parent_execution_id": None,
            "blocked_on_child_id": None,
            "data_region": "us-east-1",
            "priority": 5,
            "idempotency_key": None,
            "metadata": {},
            "owner_id": None,
            "org_id": None,
            "encrypted_state": None,
            "encryption_key_id": None,
            "error_message": None,
        }
        t = time.perf_counter()
        await provider.save_workflow(wid, data)
        times_save.append(time.perf_counter() - t)

    st = _stats(times_save)
    sec.add("save_workflow", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # get_workflow
    times_get = []
    for wid in wf_ids:
        t = time.perf_counter()
        await provider.load_workflow(wid)
        times_get.append(time.perf_counter() - t)

    st = _stats(times_get)
    sec.add("load_workflow", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # list_workflows
    list_n = max(10, n // 5)
    times_list = []
    for _ in range(list_n):
        t = time.perf_counter()
        await provider.list_workflows(limit=50)
        times_list.append(time.perf_counter() - t)

    st = _stats(times_list)
    sec.add("list_workflows(50)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    await provider.close()
    return sec


# ---------------------------------------------------------------------------
# Section 4 — E2E Workflow
# ---------------------------------------------------------------------------

async def bench_e2e_workflow(n: int) -> Section:
    sec = Section("4. E2E Workflow (InMemory + SyncExecutor)")

    from rufus.builder import WorkflowBuilder
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.observability.noop import NoopWorkflowObserver
    from rufus.implementations.persistence.memory import InMemoryPersistence
    from rufus.implementations.execution.sync import SyncExecutor
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

    persistence = InMemoryPersistence()
    await persistence.initialize()

    executor = SyncExecutor()
    # NOTE: intentional bypass of initialize(engine) — sets thread pool directly
    executor._thread_pool_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    executor._loop = asyncio.get_running_loop()

    observer = NoopWorkflowObserver()

    builder = WorkflowBuilder(
        workflow_registry={},
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    builder.reload_workflow_type("BenchmarkWorkflow", BENCH_YAML)

    # warmup
    for _ in range(5):
        wf = await builder.create_workflow(
            workflow_type="BenchmarkWorkflow",
            persistence_provider=persistence,
            execution_provider=executor,
            workflow_builder=builder,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
            workflow_observer=observer,
        )
        await wf.next_step({})

    times_create = []
    times_step = []
    run_n = max(10, n // 10)
    for _ in range(run_n):
        t = time.perf_counter()
        wf = await builder.create_workflow(
            workflow_type="BenchmarkWorkflow",
            persistence_provider=persistence,
            execution_provider=executor,
            workflow_builder=builder,
            expression_evaluator_cls=SimpleExpressionEvaluator,
            template_engine_cls=Jinja2TemplateEngine,
            workflow_observer=observer,
        )
        times_create.append(time.perf_counter() - t)

        t = time.perf_counter()
        await wf.next_step({})
        times_step.append(time.perf_counter() - t)

    st = _stats(times_create)
    sec.add("create_workflow", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])
    st = _stats(times_step)
    sec.add("next_step (2 steps)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    executor._thread_pool_executor.shutdown(wait=False)
    await persistence.close()
    return sec


# ---------------------------------------------------------------------------
# Section 5 — Async Event Loop
# ---------------------------------------------------------------------------

async def bench_event_loop(n: int) -> Section:
    sec = Section("5. Async Event Loop")

    loop = asyncio.get_running_loop()
    if _UVLOOP_AVAILABLE:
        import uvloop as _uv
        loop_label = "uvloop.Loop" if isinstance(loop, _uv.Loop) else type(loop).__name__
    else:
        loop_label = type(loop).__name__
    sec.note(f"event loop: {loop_label}")

    # warmup
    for _ in range(200):
        await asyncio.sleep(0)

    times = []
    for _ in range(n):
        t = time.perf_counter()
        await asyncio.sleep(0)
        times.append(time.perf_counter() - t)

    p50 = statistics.median(times) * 1_000_000
    p95 = _pct(times, 0.95) * 1_000_000
    p99 = _pct(times, 0.99) * 1_000_000
    sec.add(f"asyncio.sleep(0) [{loop_label}]",
            p50_us=p50, p95_us=p95, p99_us=p99)

    return sec


# ---------------------------------------------------------------------------
# Section 6 — Pydantic State Model
# ---------------------------------------------------------------------------

def bench_pydantic(n: int) -> Section:
    sec = Section("6. Pydantic State Model")

    raw = {"counter": 42, "payload": "x" * 200, "result": "done"}

    # warmup
    for _ in range(500):
        m = BenchmarkState(**raw)
        m.model_dump()

    times_validate = []
    for _ in range(n):
        t = time.perf_counter()
        BenchmarkState.model_validate(raw)
        times_validate.append(time.perf_counter() - t)

    instance = BenchmarkState(**raw)
    times_dump = []
    for _ in range(n):
        t = time.perf_counter()
        instance.model_dump()
        times_dump.append(time.perf_counter() - t)

    st = _stats(times_validate)
    sec.add("model_validate", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])
    st = _stats(times_dump)
    sec.add("model_dump", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    return sec


# ---------------------------------------------------------------------------
# Section 7 — Fernet Encryption
# ---------------------------------------------------------------------------

def bench_fernet(n: int) -> Section:
    sec = Section("7. Fernet Encryption")

    if not _CRYPTO_AVAILABLE:
        sec.note("cryptography not installed — skipping")
        return sec

    key = Fernet.generate_key()
    f = Fernet(key)

    sizes = [("100B", 100), ("1KB", 1024), ("10KB", 10 * 1024), ("100KB", 100 * 1024)]

    # Warmup: prime the cryptography library (OpenSSL, JIT, etc.) before the
    # first timed measurement so 100B isn't penalised for cold-library overhead.
    _warmup = secrets.token_bytes(100)
    for _ in range(50):
        f.decrypt(f.encrypt(_warmup))

    for label, size in sizes:
        plaintext = secrets.token_bytes(size)

        times_enc = []
        for _ in range(n):
            t = time.perf_counter()
            token = f.encrypt(plaintext)
            times_enc.append(time.perf_counter() - t)

        token = f.encrypt(plaintext)
        times_dec = []
        for _ in range(n):
            t = time.perf_counter()
            f.decrypt(token)
            times_dec.append(time.perf_counter() - t)

        st_e = _stats(times_enc)
        st_d = _stats(times_dec)
        sec.add(f"encrypt {label}",
                ops_per_sec=st_e["ops_per_sec"], p95_ms=st_e["p95_ms"])
        sec.add(f"decrypt {label}",
                ops_per_sec=st_d["ops_per_sec"], p95_ms=st_d["p95_ms"])

    return sec


# ---------------------------------------------------------------------------
# Section 8 — HMAC-SHA256
# ---------------------------------------------------------------------------

def bench_hmac(n: int) -> Section:
    sec = Section("8. HMAC-SHA256")

    key = secrets.token_bytes(32)
    payload_single = f"txn_{uuid.uuid4()}|{'x' * 64}|default".encode()
    payloads_batch = [
        f"txn_{uuid.uuid4()}|{'x' * 64}|default".encode()
        for _ in range(50)
    ]

    # single transaction HMAC
    times_single = []
    for _ in range(n):
        t = time.perf_counter()
        _hmac.new(key, payload_single, hashlib.sha256).hexdigest()
        times_single.append(time.perf_counter() - t)

    st = _stats(times_single)
    sec.add("single txn HMAC", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # batch of 50
    batch_n = max(10, n // 5)
    times_batch = []
    for _ in range(batch_n):
        t = time.perf_counter()
        for p in payloads_batch:
            _hmac.new(key, p, hashlib.sha256).hexdigest()
        times_batch.append(time.perf_counter() - t)

    st = _stats(times_batch)
    sec.add("batch-50 HMAC total",
            ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])
    sec.add("batch-50 per-txn throughput",
            ops_per_sec=st["ops_per_sec"] * 50)

    # constant-time verify — match vs mismatch variance
    tag = _hmac.new(key, payload_single, hashlib.sha256).digest()
    wrong_tag = bytes(b ^ 0xFF for b in tag)

    times_match = []
    for _ in range(n):
        t = time.perf_counter()
        _hmac.compare_digest(
            _hmac.new(key, payload_single, hashlib.sha256).digest(),
            tag,
        )
        times_match.append(time.perf_counter() - t)

    times_mismatch = []
    for _ in range(n):
        t = time.perf_counter()
        _hmac.compare_digest(
            _hmac.new(key, payload_single, hashlib.sha256).digest(),
            wrong_tag,
        )
        times_mismatch.append(time.perf_counter() - t)

    mean_match = statistics.mean(times_match) * 1e6
    mean_mismatch = statistics.mean(times_mismatch) * 1e6
    variance_pct = abs(mean_match - mean_mismatch) / max(mean_match, mean_mismatch) * 100

    sec.add("verify match", mean_us=mean_match)
    sec.add("verify mismatch", mean_us=mean_mismatch)
    sec.add("constant-time variance", variance_pct=variance_pct,
            ok="yes" if variance_pct < 5 else "WARN >5%")

    return sec


# ---------------------------------------------------------------------------
# Section 9 — Ed25519 Signatures
# ---------------------------------------------------------------------------

def bench_ed25519(n: int) -> Section:
    sec = Section("9. Ed25519 Signatures")

    if not _CRYPTO_AVAILABLE:
        sec.note("cryptography not installed — skipping")
        return sec

    payload_1kb = secrets.token_bytes(1024)

    # keygen
    keygen_n = max(20, n // 5)
    times_keygen = []
    for _ in range(keygen_n):
        t = time.perf_counter()
        Ed25519PrivateKey.generate()
        times_keygen.append(time.perf_counter() - t)

    st = _stats(times_keygen)
    sec.add("keygen", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    # sign 1KB
    times_sign = []
    for _ in range(n):
        t = time.perf_counter()
        priv.sign(payload_1kb)
        times_sign.append(time.perf_counter() - t)

    st = _stats(times_sign)
    sec.add("sign 1KB", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    sig = priv.sign(payload_1kb)
    tampered = b"X" + payload_1kb[1:]

    # verify valid
    times_verify_ok = []
    for _ in range(n):
        t = time.perf_counter()
        pub.verify(sig, payload_1kb)
        times_verify_ok.append(time.perf_counter() - t)

    st = _stats(times_verify_ok)
    sec.add("verify valid", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # verify tampered (should raise — count it)
    from cryptography.exceptions import InvalidSignature
    times_verify_bad = []
    for _ in range(n):
        t = time.perf_counter()
        try:
            pub.verify(sig, tampered)
        except InvalidSignature:
            pass
        times_verify_bad.append(time.perf_counter() - t)

    st = _stats(times_verify_bad)
    sec.add("verify tampered (rejected)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # import cold vs warm
    from rufus.builder import WorkflowBuilder
    import_path = "cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey"

    # NOTE: intentional use of private API for caching benchmark
    if import_path in WorkflowBuilder._import_cache:
        del WorkflowBuilder._import_cache[import_path]

    t = time.perf_counter()
    # NOTE: intentional use of private API for caching benchmark
    WorkflowBuilder._import_from_string(import_path)
    cold_ms = (time.perf_counter() - t) * 1000

    warm_times = []
    for _ in range(100):
        t = time.perf_counter()
        # NOTE: intentional use of private API for caching benchmark
        WorkflowBuilder._import_from_string(import_path)
        warm_times.append(time.perf_counter() - t)

    warm_ms = statistics.mean(warm_times) * 1000
    sec.add("import cold", ms=cold_ms)
    sec.add("import warm (cached)", ms=warm_ms,
            speedup=f"{cold_ms / warm_ms:.0f}x" if warm_ms > 0 else "N/A")

    return sec


# ---------------------------------------------------------------------------
# Section 10 — API Key Hashing
# ---------------------------------------------------------------------------

def bench_api_key_hashing(n: int) -> Section:
    sec = Section("10. API Key Hashing")

    # Registration cycle: generate + hash
    times_reg = []
    generated_keys = []
    for _ in range(n):
        t = time.perf_counter()
        raw_key = secrets.token_urlsafe(32)
        hashlib.sha256(raw_key.encode()).hexdigest()
        times_reg.append(time.perf_counter() - t)
        generated_keys.append(raw_key)

    st = _stats(times_reg)
    sec.add("registration (generate + hash)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # Auth cycle: hash incoming key + constant-time compare
    stored_hashes = [hashlib.sha256(k.encode()).hexdigest() for k in generated_keys]

    times_auth = []
    for raw, stored in zip(generated_keys, stored_hashes):
        t = time.perf_counter()
        incoming_hash = hashlib.sha256(raw.encode()).hexdigest()
        _hmac.compare_digest(incoming_hash, stored)
        times_auth.append(time.perf_counter() - t)

    st = _stats(times_auth)
    sec.add("auth check (hash + compare_digest)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    return sec


# ---------------------------------------------------------------------------
# Section 11 — Full SAF Pipeline
# ---------------------------------------------------------------------------

async def bench_saf_pipeline(n: int) -> Section:
    sec = Section("11. Full SAF Pipeline (encrypt + HMAC + SQLite save)")

    if not _CRYPTO_AVAILABLE:
        sec.note("cryptography not installed — skipping")
        return sec

    from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

    fernet_key = Fernet.generate_key()
    fernet = Fernet(fernet_key)
    hmac_key = secrets.token_bytes(32)

    persistence = SQLitePersistenceProvider(db_path=":memory:")
    await persistence.initialize()

    # Pre-create some workflow rows so FK is satisfied (saf table may have FK)
    wf_ids = [str(uuid.uuid4()) for _ in range(min(n, 50))]
    for wid in wf_ids:
        wf_data = {
            "id": wid, "workflow_type": "PaymentSim", "workflow_version": "v1",
            "current_step": "Step1", "status": "ACTIVE", "state": {},
            "definition_snapshot": None, "steps_config": [], "saga_mode": False,
            "state_model_path": "x.y.z", "completed_steps_stack": [],
            "parent_execution_id": None, "blocked_on_child_id": None,
            "data_region": "us-east-1", "priority": 5, "idempotency_key": None,
            "metadata": {}, "owner_id": None, "org_id": None,
            "encrypted_state": None, "encryption_key_id": None, "error_message": None,
        }
        await persistence.save_workflow(wid, wf_data)

    times_encrypt = []
    times_hmac = []
    times_total = []

    pipeline_n = max(10, n // 5)
    for i in range(pipeline_n):
        txn_id = str(uuid.uuid4())
        card_data = json.dumps({
            "pan": "4111111111111111",
            "amount_cents": 5000 + i,
            "merchant": "Test Merchant",
            "currency": "USD",
        }).encode()

        t_total = time.perf_counter()

        t = time.perf_counter()
        encrypted_blob = fernet.encrypt(card_data)
        times_encrypt.append(time.perf_counter() - t)

        t = time.perf_counter()
        hmac_input = f"{txn_id}|{encrypted_blob.hex()}|default"
        _hmac.new(hmac_key, hmac_input.encode(), hashlib.sha256).hexdigest()
        times_hmac.append(time.perf_counter() - t)

        times_total.append(time.perf_counter() - t_total)

    st_enc = _stats(times_encrypt)
    st_hmac = _stats(times_hmac)
    st_total = _stats(times_total)

    sec.add("encrypt payload (~100B)", ops_per_sec=st_enc["ops_per_sec"], p95_ms=st_enc["p95_ms"])
    sec.add("HMAC sign", ops_per_sec=st_hmac["ops_per_sec"], p95_ms=st_hmac["p95_ms"])
    sec.add("full pipeline (encrypt+HMAC)", ops_per_sec=st_total["ops_per_sec"], p95_ms=st_total["p95_ms"])

    await persistence.close()
    return sec


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def _defaults(quick: bool, override: Optional[int]) -> Dict[str, int]:
    base = {
        "json_n": 10000,
        "import_n": 1000,
        "sqlite_n": 200,
        "e2e_n": 100,
        "loop_n": 2000,
        "pydantic_n": 10000,
        "fernet_n": 500,
        "hmac_n": 5000,
        "ed25519_n": 500,
        "apikey_n": 5000,
        "saf_n": 200,
    }
    if quick:
        base = {k: max(10, v // 10) for k, v in base.items()}
    if override is not None:
        base = {k: override for k in base}
    return base


async def _run(args) -> List[Section]:
    counts = _defaults(args.quick, args.iterations)
    skip_security = args.no_security or not _CRYPTO_AVAILABLE

    sections: List[Section] = []

    print("\n" + "=" * 78)
    print("  RUFUS SDK — COMPREHENSIVE BENCHMARK SUITE")
    print("=" * 78)
    print(f"  orjson     : {'yes' if _ORJSON_AVAILABLE else 'no'}")
    print(f"  cryptography: {'yes' if _CRYPTO_AVAILABLE else 'no'}")
    print(f"  uvloop     : {'yes' if _UVLOOP_AVAILABLE else 'no'}")
    if skip_security and not args.no_security:
        print("  NOTE: cryptography not installed — sections 7–11 will be skipped")
    print()

    print("[1/11] JSON Serialization...")
    sections.append(bench_json_serialization(counts["json_n"]))

    print("[2/11] Import Caching...")
    sections.append(bench_import_caching(counts["import_n"]))

    print("[3/11] SQLite Persistence...")
    sections.append(await bench_sqlite(counts["sqlite_n"]))

    print("[4/11] E2E Workflow...")
    sections.append(await bench_e2e_workflow(counts["e2e_n"]))

    print("[5/11] Async Event Loop...")
    sections.append(await bench_event_loop(counts["loop_n"]))

    print("[6/11] Pydantic State Model...")
    sections.append(bench_pydantic(counts["pydantic_n"]))

    if skip_security:
        print("[7-11] Security sections skipped (--no-security or cryptography missing)")
        placeholder_names = [
            "7. Fernet Encryption",
            "8. HMAC-SHA256",
            "9. Ed25519 Signatures",
            "10. API Key Hashing",
            "11. Full SAF Pipeline",
        ]
        for name in placeholder_names:
            s = Section(name)
            s.note("skipped")
            sections.append(s)
    else:
        print("[7/11] Fernet Encryption...")
        sections.append(bench_fernet(counts["fernet_n"]))

        print("[8/11] HMAC-SHA256...")
        sections.append(bench_hmac(counts["hmac_n"]))

        print("[9/11] Ed25519 Signatures...")
        sections.append(bench_ed25519(counts["ed25519_n"]))

        print("[10/11] API Key Hashing...")
        sections.append(bench_api_key_hashing(counts["apikey_n"]))

        print("[11/11] Full SAF Pipeline...")
        sections.append(await bench_saf_pipeline(counts["saf_n"]))

    return sections


def main():
    parser = argparse.ArgumentParser(description="Rufus SDK benchmark suite")
    parser.add_argument("--iterations", type=int, default=None,
                        help="Override iteration count for all sections")
    parser.add_argument("--quick", action="store_true",
                        help="Run ~10%% of default iterations (~8 seconds)")
    parser.add_argument("--output", choices=["text", "json"], default="text",
                        help="Output format")
    parser.add_argument("--no-security", action="store_true",
                        help="Skip security sections 7-11")
    args = parser.parse_args()

    if _UVLOOP_AVAILABLE and not args.quick:
        import uvloop as _uvloop
        _uvloop.install()

    sections = asyncio.run(_run(args))

    if args.output == "json":
        out = []
        for sec in sections:
            out.append({"section": sec.name, "rows": sec.rows, "notes": sec.notes})
        print(json.dumps(out, indent=2))
    else:
        for sec in sections:
            _print_section(sec)
        print("\n" + "=" * 78)
        print("  DONE")
        print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
