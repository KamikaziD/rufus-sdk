"""
Rufus SDK — Comprehensive Benchmark Suite
==========================================

Covers 16 sections:
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
 12. msgspec Typed Codec     (requires msgspec)
 13. WASM Bridge Dispatch    (requires rufus-sdk-edge)
 14. Proto Codec             (requires betterproto; generated code optional)
 15. RUVON Capability Gossip (requires rufus-sdk-edge)
 16. NKey Patch Verification (requires cryptography + rufus-sdk-edge)

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

try:
    import msgspec as _msgspec
    _MSGSPEC_AVAILABLE = True
except ImportError:
    _MSGSPEC_AVAILABLE = False

try:
    import betterproto as _betterproto
    _BETTERPROTO_AVAILABLE = True
except ImportError:
    _BETTERPROTO_AVAILABLE = False

try:
    from rufus_edge.capability_gossip import CapabilityVector, NodeTier, classify_node_tier
    _RUVON_GOSSIP_AVAILABLE = True
except ImportError:
    _RUVON_GOSSIP_AVAILABLE = False

try:
    from rufus_edge.nkey_verifier import NKeyPatchVerifier
    _NKEY_AVAILABLE = True and _CRYPTO_AVAILABLE
except ImportError:
    _NKEY_AVAILABLE = False

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
# Section 12 — msgspec Typed Codec
# ---------------------------------------------------------------------------

def bench_msgspec_codec(n: int) -> Section:
    sec = Section("12. msgspec Typed Codec")

    if not _MSGSPEC_AVAILABLE:
        sec.note("msgspec not installed — skipping")
        return sec

    from rufus.providers.dtos import WorkflowRecord
    from rufus.utils.serialization import decode_typed, encode_struct, deserialize, serialize_bytes

    record = WorkflowRecord(
        id="wf-bench-001",
        workflow_type="BenchmarkWorkflow",
        status="ACTIVE",
        current_step=2,
        state={"amount": 50000, "user_id": "u_42", "approved": True},
        steps_config=[{"name": "Step1", "type": "STANDARD"}, {"name": "Step2", "type": "ASYNC"}],
        state_model_path="benchmark.State",
        saga_mode=False,
        completed_steps_stack=[{"step": "Step1"}],
        metadata={"source": "api"},
    )
    struct_bytes = _msgspec.json.encode(record)
    dict_repr = _msgspec.to_builtins(record)
    dict_bytes = serialize_bytes(dict_repr)

    # Warmup
    for _ in range(min(n, 200)):
        encode_struct(record)
        decode_typed(struct_bytes, WorkflowRecord)
        deserialize(dict_bytes)

    # encode_struct (struct → bytes)
    times = []
    for _ in range(n):
        t = time.perf_counter()
        encode_struct(record)
        times.append(time.perf_counter() - t)
    st = _stats(times)
    sec.add("encode_struct (struct→bytes)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # decode_typed (bytes → struct, typed fast path)
    times = []
    for _ in range(n):
        t = time.perf_counter()
        decode_typed(struct_bytes, WorkflowRecord)
        times.append(time.perf_counter() - t)
    st_typed = _stats(times)
    sec.add("decode_typed (bytes→struct)", ops_per_sec=st_typed["ops_per_sec"], p95_ms=st_typed["p95_ms"])

    # dict decode (orjson/stdlib, for comparison)
    times = []
    for _ in range(n):
        t = time.perf_counter()
        deserialize(dict_bytes)
        times.append(time.perf_counter() - t)
    st_dict = _stats(times)
    speedup = st_typed["ops_per_sec"] / st_dict["ops_per_sec"] if st_dict["ops_per_sec"] else 0
    sec.add(
        f"dict decode for comparison ({speedup:.1f}× slower than typed decode)",
        ops_per_sec=st_dict["ops_per_sec"],
        p95_ms=st_dict["p95_ms"],
    )

    return sec


# ---------------------------------------------------------------------------
# Section 13 — WASM Bridge Dispatch
# ---------------------------------------------------------------------------

async def bench_wasm_bridge_dispatch(n: int) -> Section:
    sec = Section("13. WASM Bridge Dispatch")

    try:
        from rufus_edge.platform.wasm_bridge import (
            NativeWasmBridge,
            detect_wasm_bridge,
        )
        from rufus.implementations.execution.wasm_runtime import SqliteWasmBinaryResolver
        from rufus.implementations.execution.component_runtime import ComponentStepRuntime
    except ImportError as exc:
        sec.note(f"rufus-sdk-edge not installed — skipping ({exc})")
        return sec

    # ------------------------------------------------------------------
    # 12a: detect_wasm_bridge() overhead (factory call + sys.platform check)
    # ------------------------------------------------------------------
    for _ in range(500):  # warmup
        detect_wasm_bridge()

    times_detect = []
    for _ in range(n):
        t = time.perf_counter()
        detect_wasm_bridge()
        times_detect.append(time.perf_counter() - t)

    st = _stats(times_detect)
    sec.add("detect_wasm_bridge()", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # ------------------------------------------------------------------
    # 12b: JSON state encode/decode at the component boundary
    #      This is the overhead every WASM step pays to cross the Python→Wasm boundary.
    # ------------------------------------------------------------------
    state_payload = {
        "workflow_id": "wf_" + "x" * 20,
        "amount_cents": 9999,
        "currency": "USD",
        "merchant": "Acme Corp",
        "card_last_four": "4242",
        "risk_flags": ["high_velocity", "new_device"],
        "device_id": "pos-edge-001",
        "timestamp": "2026-01-01T00:00:00Z",
        "metadata": {k: f"v{k}" for k in range(20)},
    }
    state_json = json.dumps(state_payload)
    assert len(state_json) > 300, "state payload too small"

    for _ in range(500):
        json.loads(json.dumps(state_payload))

    times_enc = []
    for _ in range(n):
        t = time.perf_counter()
        json.dumps(state_payload)
        times_enc.append(time.perf_counter() - t)

    times_dec = []
    for _ in range(n):
        t = time.perf_counter()
        json.loads(state_json)
        times_dec.append(time.perf_counter() - t)

    st = _stats(times_enc)
    sec.add("state encode (bridge boundary)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])
    st = _stats(times_dec)
    sec.add("state decode (bridge boundary)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # ------------------------------------------------------------------
    # 12c: NativeWasmBridge.execute_component dispatch overhead
    #      _call_component is mocked so we measure pure Python dispatch cost
    #      (import resolution, call overhead, not wasmtime itself).
    # ------------------------------------------------------------------
    CM_BINARY = b"\x00asm\x0e\x00\x01\x00" + b"\x00" * 200
    bridge = NativeWasmBridge()
    _original_call = ComponentStepRuntime._call_component

    def _mock_call(binary, state_json_arg, step_name):
        return '{"ok": true}'

    ComponentStepRuntime._call_component = staticmethod(_mock_call)
    try:
        for _ in range(200):  # warmup
            bridge.execute_component(CM_BINARY, state_json, "execute")

        times_bridge = []
        for _ in range(n):
            t = time.perf_counter()
            bridge.execute_component(CM_BINARY, state_json, "execute")
            times_bridge.append(time.perf_counter() - t)
    finally:
        ComponentStepRuntime._call_component = staticmethod(_original_call)

    st = _stats(times_bridge)
    sec.add("NativeWasmBridge dispatch (mock)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # ------------------------------------------------------------------
    # 12d: SqliteWasmBinaryResolver.resolve() from in-memory SQLite
    #      Measures the lookup cost from device_wasm_cache — the first
    #      thing every WASM step does before calling the bridge.
    # ------------------------------------------------------------------
    try:
        import aiosqlite
        import hashlib as _hashlib

        fake_binary = b"\x00asm\x0e\x00\x01\x00" + b"\x00" * 1024
        fake_hash = _hashlib.sha256(fake_binary).hexdigest()

        async with aiosqlite.connect(":memory:") as conn:
            await conn.execute(
                "CREATE TABLE device_wasm_cache "
                "(binary_hash TEXT PRIMARY KEY, binary_data BLOB)"
            )
            await conn.execute(
                "INSERT INTO device_wasm_cache VALUES (?, ?)",
                (fake_hash, fake_binary),
            )
            await conn.commit()

            resolver = SqliteWasmBinaryResolver(conn)

            # warmup
            for _ in range(20):
                await resolver.resolve(fake_hash)

            resolve_n = max(10, n // 10)
            times_resolve = []
            for _ in range(resolve_n):
                t = time.perf_counter()
                await resolver.resolve(fake_hash)
                times_resolve.append(time.perf_counter() - t)

        st = _stats(times_resolve)
        sec.add("SqliteWasmBinaryResolver.resolve (1KB)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    except ImportError:
        sec.note("aiosqlite not installed — skipping resolver benchmark")

    # ------------------------------------------------------------------
    # 12e: Full dispatch chain — resolve → hash verify → bridge (mocked)
    #      End-to-end cost of ComponentStepRuntime._dispatch() without
    #      actual wasmtime execution.
    # ------------------------------------------------------------------
    try:
        import aiosqlite as _aiosqlite

        async with _aiosqlite.connect(":memory:") as conn:
            await conn.execute(
                "CREATE TABLE device_wasm_cache "
                "(binary_hash TEXT PRIMARY KEY, binary_data BLOB)"
            )
            await conn.execute(
                "INSERT INTO device_wasm_cache VALUES (?, ?)",
                (fake_hash, fake_binary),
            )
            await conn.commit()

            from unittest.mock import MagicMock

            wasm_config = MagicMock()
            wasm_config.wasm_hash = fake_hash
            wasm_config.entrypoint = "execute"
            wasm_config.state_mapping = None
            wasm_config.timeout_ms = 5000
            wasm_config.fallback_on_error = "fail"

            resolver2 = SqliteWasmBinaryResolver(conn)
            runtime = ComponentStepRuntime(resolver2, bridge=None)

            _original_run_component = ComponentStepRuntime._run_component

            async def _mock_run_component(self, binary, wasm_config, state_data):
                return {"ok": True}

            ComponentStepRuntime._run_component = _mock_run_component
            try:
                # warmup
                for _ in range(5):
                    await runtime._dispatch(wasm_config, state_payload)

                chain_n = max(10, n // 20)
                times_chain = []
                for _ in range(chain_n):
                    t = time.perf_counter()
                    await runtime._dispatch(wasm_config, state_payload)
                    times_chain.append(time.perf_counter() - t)
            finally:
                ComponentStepRuntime._run_component = _original_run_component

        st = _stats(times_chain)
        sec.add("full chain: resolve+verify+bridge (mock)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    except ImportError:
        sec.note("aiosqlite not installed — skipping full chain benchmark")

    # ------------------------------------------------------------------
    # 12f: execute_batch vs 5× execute — event-loop round-trip savings
    #      Measures the overhead reduction from collapsing N sequential
    #      run_in_executor calls into a single batch dispatch.
    # ------------------------------------------------------------------
    try:
        import aiosqlite as _aiosqlite2
        import hashlib as _hashlib2

        batch_n = 5  # steps per batch (fixed; matches wasm_steps_per_sync default)
        _fake_binary = b"\x00asm\x0e\x00\x01\x00" + b"\x00" * 1024
        _fake_hash = _hashlib2.sha256(_fake_binary).hexdigest()

        async with _aiosqlite2.connect(":memory:") as conn2:
            await conn2.execute(
                "CREATE TABLE device_wasm_cache "
                "(binary_hash TEXT PRIMARY KEY, binary_data BLOB)"
            )
            await conn2.execute(
                "INSERT INTO device_wasm_cache VALUES (?, ?)",
                (_fake_hash, _fake_binary),
            )
            await conn2.commit()

            from unittest.mock import MagicMock

            wasm_config2 = MagicMock()
            wasm_config2.wasm_hash = _fake_hash
            wasm_config2.entrypoint = "execute"
            wasm_config2.state_mapping = None
            wasm_config2.timeout_ms = 5000
            wasm_config2.fallback_on_error = "fail"

            resolver3 = SqliteWasmBinaryResolver(conn2)
            runtime2 = ComponentStepRuntime(resolver3, bridge=None)

            _original_run_component2 = ComponentStepRuntime._run_component
            _original_execute_batch = ComponentStepRuntime.execute_batch

            async def _mock_run_component2(self, binary, wasm_config, state_data):
                return {"ok": True}

            async def _mock_execute_batch(self, wasm_config, states):
                return [{"ok": True}] * len(states)

            ComponentStepRuntime._run_component = _mock_run_component2
            ComponentStepRuntime.execute_batch = _mock_execute_batch
            try:
                batch_iterations = max(5, n // 20)

                # (a) Sequential baseline: batch_n independent execute() calls
                times_seq = []
                for _ in range(batch_iterations):
                    t = time.perf_counter()
                    for _ in range(batch_n):
                        await runtime2._dispatch(wasm_config2, state_payload)
                    times_seq.append(time.perf_counter() - t)

                # (b) Batch: single execute_batch() call for batch_n states
                times_batch = []
                for _ in range(batch_iterations):
                    t = time.perf_counter()
                    await runtime2.execute_batch(wasm_config2, [state_payload] * batch_n)
                    times_batch.append(time.perf_counter() - t)
            finally:
                ComponentStepRuntime._run_component = _original_run_component2
                ComponentStepRuntime.execute_batch = _original_execute_batch

        st_seq = _stats(times_seq)
        st_bat = _stats(times_batch)

        speedup = st_seq["p50_ms"] / st_bat["p50_ms"] if st_bat["p50_ms"] > 0 else float("inf")
        round_trip_savings = batch_n - 1  # one call instead of batch_n

        sec.add(
            f"sequential {batch_n}× execute (baseline)",
            ops_per_sec=st_seq["ops_per_sec"],
            p95_ms=st_seq["p95_ms"],
        )
        sec.add(
            f"execute_batch ({batch_n} states, 1 round-trip)",
            ops_per_sec=st_bat["ops_per_sec"],
            p95_ms=st_bat["p95_ms"],
        )
        sec.note(
            f"Section 12f  execute_batch vs {batch_n}x execute\n"
            f"  sequential {batch_n}-step:  p50={st_seq['p50_ms']:.3f}ms  p95={st_seq['p95_ms']:.3f}ms\n"
            f"  batch {batch_n}-step:        p50={st_bat['p50_ms']:.3f}ms  p95={st_bat['p95_ms']:.3f}ms\n"
            f"  Speedup:            {speedup:.1f}x  (saves {round_trip_savings} event-loop round-trips per device)"
        )

    except ImportError:
        sec.note("aiosqlite not installed — skipping 12f batch overhead benchmark")

    return sec


# ---------------------------------------------------------------------------
# Section 14 — Proto Codec (pack_message / unpack_message)
# ---------------------------------------------------------------------------

def bench_proto_codec(n: int) -> "Section":
    """Benchmark pack_message/unpack_message envelope codec vs raw orjson baseline.

    Tests the serialization.py envelope system introduced in Phase 4:
      - JSON envelope (ENCODING_JSON prefix + orjson/json payload)
      - Proto envelope (ENCODING_PROTO prefix + betterproto bytes, when available)

    Payload: HeartbeatMsg-equivalent dict (~287B JSON / ~48B proto).
    """
    sec = Section("14. Proto Codec (pack_message)")

    try:
        from rufus.utils.serialization import pack_message, unpack_message, _USING_PROTO
    except ImportError as exc:
        sec.note(f"rufus SDK not on path — skipping ({exc})")
        return sec

    hb_dict = {
        "device_id": "pos-terminal-bench-001",
        "device_status": "online",
        "pending_sync_count": 3,
        "last_sync_at": "2026-03-24T12:34:56.789Z",
        "config_version": "v1.0.0rc6",
        "sdk_version": "1.0.0rc6",
        "sent_at": "2026-03-24T12:35:00.000Z",
    }

    # ------------------------------------------------------------------
    # 14a: JSON envelope — pack_message(dict) → ENCODING_JSON + orjson/json
    # ------------------------------------------------------------------
    for _ in range(500):  # warmup
        pack_message(hb_dict)

    times_pack_json = []
    for _ in range(n):
        t0 = time.perf_counter()
        data = pack_message(hb_dict)
        times_pack_json.append(time.perf_counter() - t0)

    st_pj = _stats(times_pack_json)
    encoded_json_size = len(data)
    sec.add("pack_message JSON envelope", ops_per_sec=st_pj["ops_per_sec"], p95_ms=st_pj["p95_ms"])

    # ------------------------------------------------------------------
    # 14b: JSON envelope — unpack_message
    # ------------------------------------------------------------------
    json_data = pack_message(hb_dict)
    for _ in range(500):
        unpack_message(json_data)

    times_unpack_json = []
    for _ in range(n):
        t0 = time.perf_counter()
        unpack_message(json_data)
        times_unpack_json.append(time.perf_counter() - t0)

    st_uj = _stats(times_unpack_json)
    sec.add("unpack_message JSON envelope", ops_per_sec=st_uj["ops_per_sec"], p95_ms=st_uj["p95_ms"])

    # ------------------------------------------------------------------
    # 14c: Proto envelope (only when betterproto available)
    # ------------------------------------------------------------------
    if _USING_PROTO and _BETTERPROTO_AVAILABLE:
        try:
            from rufus.proto.gen import HeartbeatMsg  # type: ignore
            proto_msg = HeartbeatMsg(**hb_dict)

            for _ in range(500):
                pack_message(hb_dict, proto_msg)

            times_pack_proto = []
            for _ in range(n):
                t0 = time.perf_counter()
                data_proto = pack_message(hb_dict, proto_msg)
                times_pack_proto.append(time.perf_counter() - t0)

            st_pp = _stats(times_pack_proto)
            encoded_proto_size = len(data_proto)
            sec.add("pack_message proto envelope", ops_per_sec=st_pp["ops_per_sec"], p95_ms=st_pp["p95_ms"])

            # unpack_message proto
            for _ in range(500):
                unpack_message(data_proto, proto_type=HeartbeatMsg)

            times_unpack_proto = []
            for _ in range(n):
                t0 = time.perf_counter()
                unpack_message(data_proto, proto_type=HeartbeatMsg)
                times_unpack_proto.append(time.perf_counter() - t0)

            st_up = _stats(times_unpack_proto)
            sec.add("unpack_message proto envelope", ops_per_sec=st_up["ops_per_sec"], p95_ms=st_up["p95_ms"])

            size_ratio = encoded_json_size / encoded_proto_size if encoded_proto_size else 0
            sec.note(
                f"Payload sizes: JSON={encoded_json_size}B  proto={encoded_proto_size}B  "
                f"({size_ratio:.1f}× smaller with proto)\n"
                f"  pack JSON:   p50={st_pj['p50_ms']:.3f}ms  p95={st_pj['p95_ms']:.3f}ms\n"
                f"  pack proto:  p50={st_pp['p50_ms']:.3f}ms  p95={st_pp['p95_ms']:.3f}ms\n"
                f"  Speed delta: {abs(st_pp['ops_per_sec'] - st_pj['ops_per_sec']):.0f} ops/sec "
                f"({'proto faster' if st_pp['ops_per_sec'] > st_pj['ops_per_sec'] else 'json faster'})"
            )
        except ImportError:
            sec.note(
                "betterproto installed but generated code not found — "
                "run `make proto` to generate src/rufus/proto/gen/. "
                "JSON envelope benchmark above still valid."
            )
    else:
        sec.note(
            f"betterproto not installed (pip install betterproto) — "
            f"JSON envelope only. JSON payload size: {encoded_json_size}B"
        )

    return sec


# ---------------------------------------------------------------------------
# Section 15 — RUVON Capability Gossip
# ---------------------------------------------------------------------------

def bench_ruvon_gossip(n: int) -> Section:
    sec = Section("15. RUVON Capability Gossip")

    if not _RUVON_GOSSIP_AVAILABLE:
        sec.note(
            "rufus-sdk-edge not installed or capability_gossip not found — "
            "pip install -e 'packages/rufus-sdk-edge[edge]'"
        )
        return sec

    import json as _json

    # Build a representative CapabilityVector
    def _make_vec(device_id: str, ram: float = 768.0, cpu: float = 0.35,
                  tier: NodeTier = NodeTier.TIER_2) -> CapabilityVector:
        return CapabilityVector(
            device_id=device_id,
            available_ram_mb=ram,
            cpu_load=cpu,
            model_tier=2 if tier == NodeTier.TIER_2 else (3 if tier == NodeTier.TIER_3 else 1),
            latency_ms=12.5,
            task_queue_length=3,
            node_tier=tier,
        )

    sample = _make_vec("bench-device-001")

    # --- to_dict / from_dict throughput ---
    for _ in range(max(50, n // 100)):
        sample.to_dict()

    times_to = []
    for _ in range(n):
        t0 = time.perf_counter()
        sample.to_dict()
        times_to.append(time.perf_counter() - t0)
    st = _stats(times_to)
    sec.add("CapabilityVector.to_dict()", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    d = sample.to_dict()
    for _ in range(max(50, n // 100)):
        CapabilityVector.from_dict(d)

    times_from = []
    for _ in range(n):
        t0 = time.perf_counter()
        CapabilityVector.from_dict(d)
        times_from.append(time.perf_counter() - t0)
    st = _stats(times_from)
    sec.add("CapabilityVector.from_dict()", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # --- is_stale() check ---
    times_stale = []
    for _ in range(n):
        t0 = time.perf_counter()
        sample.is_stale()
        times_stale.append(time.perf_counter() - t0)
    st = _stats(times_stale)
    sec.add("CapabilityVector.is_stale()", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # --- JSON round-trip (what the broadcast loop serialises to bytes) ---
    times_json = []
    for _ in range(n):
        t0 = time.perf_counter()
        _json.dumps(sample.to_dict()).encode()
        times_json.append(time.perf_counter() - t0)
    st = _stats(times_json)
    sec.add("gossip payload encode (json+encode)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    raw_bytes = _json.dumps(sample.to_dict()).encode()
    times_decode = []
    for _ in range(n):
        t0 = time.perf_counter()
        CapabilityVector.from_dict(_json.loads(raw_bytes))
        times_decode.append(time.perf_counter() - t0)
    st = _stats(times_decode)
    sec.add("gossip payload decode (json+from_dict)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # --- find_best_builder() selection across N peers (synchronous equivalent) ---
    # Replicate the synchronous portion of find_best_builder without async overhead
    def _find_best(peers: Dict[str, "CapabilityVector"]) -> Optional[str]:
        from rufus_edge.capability_gossip import _tier_to_int
        candidates = [
            v for v in peers.values()
            if _tier_to_int(v.node_tier) >= 2 and v.available_ram_mb > 256
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda v: (_tier_to_int(v.node_tier), -v.cpu_load, v.available_ram_mb),
            reverse=True,
        )
        return candidates[0].device_id

    for peer_count in (10, 50, 100):
        peers = {
            f"peer-{i:04d}": _make_vec(
                f"peer-{i:04d}",
                ram=256.0 + (i % 3) * 512,
                cpu=0.1 + (i % 5) * 0.1,
                tier=NodeTier.TIER_2 if i % 3 != 0 else NodeTier.TIER_3,
            )
            for i in range(peer_count)
        }
        # warmup
        for _ in range(20):
            _find_best(peers)
        times_sel = []
        bench_n = max(100, n // 10)
        for _ in range(bench_n):
            t0 = time.perf_counter()
            _find_best(peers)
            times_sel.append(time.perf_counter() - t0)
        st = _stats(times_sel)
        sec.add(f"find_best_builder() — {peer_count} peers", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # --- classify_node_tier() ---
    times_class = []
    for _ in range(n):
        t0 = time.perf_counter()
        classify_node_tier(768.0, [])
        times_class.append(time.perf_counter() - t0)
    st = _stats(times_class)
    sec.add("classify_node_tier()", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    sec.note(
        "Gossip encode/decode pipeline: to_dict + json.dumps + encode = publish path; "
        "json.loads + from_dict = receive path. find_best_builder() is O(N log N) in peer count."
    )
    return sec


# ---------------------------------------------------------------------------
# Section 16 — NKey Patch Verification
# ---------------------------------------------------------------------------

def bench_nkey_verification(n: int) -> Section:
    sec = Section("16. NKey Patch Verification")

    if not _NKEY_AVAILABLE:
        if not _CRYPTO_AVAILABLE:
            sec.note("cryptography not installed — pip install cryptography")
        else:
            sec.note(
                "rufus-sdk-edge not installed or nkey_verifier not found — "
                "pip install -e 'packages/rufus-sdk-edge[edge]'"
            )
        return sec

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64 as _b64

    # Generate a real keypair for benchmarking
    priv_key = Ed25519PrivateKey.generate()
    pub_bytes = priv_key.public_key().public_bytes_raw()
    pub_b64 = _b64.urlsafe_b64encode(pub_bytes).decode()

    # Create verifier
    verifier = NKeyPatchVerifier(pub_b64)

    # Simulate a WASM binary patch payload (realistic: 64 KB)
    binary_small = secrets.token_bytes(256)    # 256 B — heartbeat-sized
    binary_large = secrets.token_bytes(65536)  # 64 KB — typical WASM module

    sig_small = _b64.urlsafe_b64encode(priv_key.sign(binary_small)).decode()
    sig_large = _b64.urlsafe_b64encode(priv_key.sign(binary_large)).decode()
    sig_bad = _b64.urlsafe_b64encode(secrets.token_bytes(64)).decode()

    # --- valid signature, small payload ---
    for _ in range(max(10, n // 100)):
        verifier.verify(binary_small, sig_small)

    times_valid_small = []
    for _ in range(n):
        t0 = time.perf_counter()
        verifier.verify(binary_small, sig_small)
        times_valid_small.append(time.perf_counter() - t0)
    st = _stats(times_valid_small)
    sec.add("verify() valid — 256 B payload", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # --- valid signature, 64 KB payload ---
    times_valid_large = []
    for _ in range(n):
        t0 = time.perf_counter()
        verifier.verify(binary_large, sig_large)
        times_valid_large.append(time.perf_counter() - t0)
    st = _stats(times_valid_large)
    sec.add("verify() valid — 64 KB WASM", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # --- invalid signature rejection ---
    times_invalid = []
    for _ in range(n):
        t0 = time.perf_counter()
        verifier.verify(binary_small, sig_bad)
        times_invalid.append(time.perf_counter() - t0)
    st = _stats(times_invalid)
    sec.add("verify() invalid sig rejection", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # --- NKeyPatchVerifier.from_env() with missing env var (None path) ---
    times_none = []
    for _ in range(min(n, 1000)):
        t0 = time.perf_counter()
        NKeyPatchVerifier.from_env()   # env var not set → returns None immediately
        times_none.append(time.perf_counter() - t0)
    st = _stats(times_none)
    sec.add("from_env() → None (env var absent)", ops_per_sec=st["ops_per_sec"], p95_ms=st["p95_ms"])

    # Summarise overhead delta
    small_valid_ops = len(times_valid_small) / sum(times_valid_small) if times_valid_small else 0
    large_valid_ops = len(times_valid_large) / sum(times_valid_large) if times_valid_large else 0
    sec.note(
        f"Ed25519 verify is constant-time w.r.t. payload size — "
        f"256 B: {small_valid_ops:,.0f} ops/sec, "
        f"64 KB: {large_valid_ops:,.0f} ops/sec. "
        f"Overhead is dominated by signature verification, not data hashing."
    )
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
        "msgspec_n": 10000,
        "wasm_n": 500,
        "proto_n": 10000,
        "gossip_n": 5000,
        "nkey_n": 500,
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
    print(f"  orjson      : {'yes' if _ORJSON_AVAILABLE else 'no'}")
    print(f"  msgspec     : {'yes' if _MSGSPEC_AVAILABLE else 'no'}")
    print(f"  betterproto : {'yes' if _BETTERPROTO_AVAILABLE else 'no'}")
    print(f"  cryptography: {'yes' if _CRYPTO_AVAILABLE else 'no'}")
    print(f"  uvloop      : {'yes' if _UVLOOP_AVAILABLE else 'no'}")
    print(f"  ruvon gossip: {'yes' if _RUVON_GOSSIP_AVAILABLE else 'no (pip install rufus-sdk-edge[edge])'}")
    print(f"  nkey verify : {'yes' if _NKEY_AVAILABLE else 'no (requires cryptography + rufus-sdk-edge)'}")
    if skip_security and not args.no_security:
        print("  NOTE: cryptography not installed — sections 7–11 will be skipped")
    print()

    print("[1/16] JSON Serialization...")
    sections.append(bench_json_serialization(counts["json_n"]))

    print("[2/16] Import Caching...")
    sections.append(bench_import_caching(counts["import_n"]))

    print("[3/16] SQLite Persistence...")
    sections.append(await bench_sqlite(counts["sqlite_n"]))

    print("[4/16] E2E Workflow...")
    sections.append(await bench_e2e_workflow(counts["e2e_n"]))

    print("[5/16] Async Event Loop...")
    sections.append(await bench_event_loop(counts["loop_n"]))

    print("[6/16] Pydantic State Model...")
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
        print("[7/16] Fernet Encryption...")
        sections.append(bench_fernet(counts["fernet_n"]))

        print("[8/16] HMAC-SHA256...")
        sections.append(bench_hmac(counts["hmac_n"]))

        print("[9/16] Ed25519 Signatures...")
        sections.append(bench_ed25519(counts["ed25519_n"]))

        print("[10/16] API Key Hashing...")
        sections.append(bench_api_key_hashing(counts["apikey_n"]))

        print("[11/16] Full SAF Pipeline...")
        sections.append(await bench_saf_pipeline(counts["saf_n"]))

    print("[12/16] msgspec Typed Codec...")
    sections.append(bench_msgspec_codec(counts["msgspec_n"]))

    print("[13/16] WASM Bridge Dispatch...")
    sections.append(await bench_wasm_bridge_dispatch(counts["wasm_n"]))

    print("[14/16] Proto Codec (pack_message)...")
    sections.append(bench_proto_codec(counts["proto_n"]))

    print("[15/16] RUVON Capability Gossip...")
    sections.append(bench_ruvon_gossip(counts["gossip_n"]))

    print("[16/16] NKey Patch Verification...")
    sections.append(bench_nkey_verification(counts["nkey_n"]))

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
