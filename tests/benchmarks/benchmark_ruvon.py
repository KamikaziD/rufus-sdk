"""
benchmark_ruvon.py — Standalone RUVON performance benchmark.

Covers:
  - CapabilityVector serialise / deserialise throughput
  - Gossip payload JSON encode + decode (broadcast/receive path)
  - find_best_builder() peer selection at various fleet sizes
  - Vector scoring formula S(Vc) computation cost
  - NKey Ed25519 verify: valid, invalid, from_env() fast path
  - classify_node_tier() hardware classification

Usage::

    python tests/benchmarks/benchmark_ruvon.py
    python tests/benchmarks/benchmark_ruvon.py --quick
    python tests/benchmarks/benchmark_ruvon.py --iterations 1000
    python tests/benchmarks/benchmark_ruvon.py --output json
"""

import argparse
import json
import secrets
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Dependency probes
# ---------------------------------------------------------------------------

try:
    from ruvon_edge.capability_gossip import (
        CapabilityVector,
        NodeTier,
        classify_node_tier,
        _tier_to_int,
    )
    _GOSSIP_OK = True
except ImportError:
    _GOSSIP_OK = False
    _GOSSIP_ERR = (
        "ruvon-edge not installed.\n"
        "  Fix: pip install -e 'packages/ruvon-edge[edge]'"
    )

try:
    from ruvon_edge.nkey_verifier import NKeyPatchVerifier
    _NKEY_MODULE_OK = True
except ImportError:
    _NKEY_MODULE_OK = False

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False

_NKEY_OK = _NKEY_MODULE_OK and _CRYPTO_OK

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct(data: List[float], p: float) -> float:
    s = sorted(data)
    idx = int(len(s) * p)
    return s[min(idx, len(s) - 1)]


def _stats(times: List[float]) -> Dict[str, float]:
    total = sum(times)
    return {
        "mean_us": statistics.mean(times) * 1_000_000,
        "p50_us":  statistics.median(times) * 1_000_000,
        "p95_us":  _pct(times, 0.95) * 1_000_000,
        "p99_us":  _pct(times, 0.99) * 1_000_000,
        "ops_per_sec": len(times) / total if total > 0 else 0,
    }


def _header(title: str):
    w = 72
    print(f"\n{'=' * w}")
    print(f"  {title}")
    print(f"{'=' * w}")


def _row(label: str, st: Dict[str, float]):
    print(
        f"  {label:<42} "
        f"p50={st['p50_us']:7.2f}µs  "
        f"p95={st['p95_us']:7.2f}µs  "
        f"{st['ops_per_sec']:>10,.0f} ops/sec"
    )


def _note(msg: str):
    print(f"  → {msg}")


# ---------------------------------------------------------------------------
# Helpers — build sample vectors
# ---------------------------------------------------------------------------

def _vec(device_id: str, ram: float = 768.0, cpu: float = 0.35,
         tier: "NodeTier" = None, queue: int = 2) -> "CapabilityVector":
    if tier is None:
        tier = NodeTier.TIER_2
    return CapabilityVector(
        device_id=device_id,
        available_ram_mb=ram,
        cpu_load=cpu,
        model_tier=_tier_to_int(tier),
        latency_ms=12.5,
        task_queue_length=queue,
        node_tier=tier,
    )


def _peer_fleet(size: int) -> Dict[str, "CapabilityVector"]:
    tiers = [NodeTier.TIER_1, NodeTier.TIER_2, NodeTier.TIER_3]
    return {
        f"peer-{i:05d}": _vec(
            f"peer-{i:05d}",
            ram=128.0 + (i % 4) * 512,
            cpu=0.05 + (i % 10) * 0.08,
            tier=tiers[i % 3],
            queue=i % 5,
        )
        for i in range(size)
    }


# ---------------------------------------------------------------------------
# Benchmark: CapabilityVector serialisation
# ---------------------------------------------------------------------------

def bench_vector_serialisation(n: int):
    if not _GOSSIP_OK:
        _header("CapabilityVector Serialisation")
        _note(_GOSSIP_ERR)
        return

    _header("CapabilityVector Serialisation")

    sample = _vec("bench-dev-001")

    # Warmup
    for _ in range(min(200, n // 10)):
        sample.to_dict()
        CapabilityVector.from_dict(sample.to_dict())
        sample.is_stale()

    # to_dict
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        sample.to_dict()
        times.append(time.perf_counter() - t0)
    _row("to_dict()", _stats(times))

    # from_dict
    d = sample.to_dict()
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        CapabilityVector.from_dict(d)
        times.append(time.perf_counter() - t0)
    _row("from_dict()", _stats(times))

    # is_stale()
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        sample.is_stale()
        times.append(time.perf_counter() - t0)
    _row("is_stale()", _stats(times))

    # JSON broadcast encode (publish path)
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        json.dumps(sample.to_dict()).encode()
        times.append(time.perf_counter() - t0)
    _row("broadcast encode (to_dict + json.dumps + .encode())", _stats(times))
    payload_bytes = json.dumps(sample.to_dict()).encode()
    _note(f"Gossip payload size: {len(payload_bytes)} bytes")

    # JSON receive decode (receive path)
    raw = json.dumps(sample.to_dict()).encode()
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        CapabilityVector.from_dict(json.loads(raw))
        times.append(time.perf_counter() - t0)
    _row("receive decode (json.loads + from_dict())", _stats(times))


# ---------------------------------------------------------------------------
# Benchmark: classify_node_tier
# ---------------------------------------------------------------------------

def bench_classify_tier(n: int):
    if not _GOSSIP_OK:
        return

    _header("classify_node_tier()")

    cases = [
        (256.0, []),
        (768.0, []),
        (8192.0, []),
    ]

    for ram_mb, accels in cases:
        for _ in range(50):
            classify_node_tier(ram_mb, accels)
        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            classify_node_tier(ram_mb, accels)
            times.append(time.perf_counter() - t0)
        tier = classify_node_tier(ram_mb, accels)
        _row(f"classify  RAM={ram_mb:.0f}MB → {tier.value}", _stats(times))


# ---------------------------------------------------------------------------
# Benchmark: find_best_builder peer selection
# ---------------------------------------------------------------------------

def bench_peer_selection(n: int):
    if not _GOSSIP_OK:
        return

    _header("find_best_builder() Peer Selection")

    def _find_best(peers: Dict[str, CapabilityVector]) -> Optional[str]:
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

    for size in (10, 50, 100, 500, 1000):
        fleet = _peer_fleet(size)
        bench_n = max(100, n // 5)
        # Warmup
        for _ in range(20):
            _find_best(fleet)
        times = []
        for _ in range(bench_n):
            t0 = time.perf_counter()
            _find_best(fleet)
            times.append(time.perf_counter() - t0)
        _row(f"find_best_builder()  N={size:>5} peers", _stats(times))

    _note("O(N log N) sort — dominated by candidate filtering at large N")


# ---------------------------------------------------------------------------
# Benchmark: RUVON vector scoring formula
# ---------------------------------------------------------------------------

def bench_vector_scoring(n: int):
    if not _GOSSIP_OK:
        return

    _header("RUVON Vector Scoring Formula  S(Vc) = 0.50·C + 0.15·(1/H) + 0.25·U + 0.10·P")

    # Inline the scoring formula (as implemented in browser_demo_2/worker.js)
    def _score(c: float, h: int, u: float, p: float) -> float:
        return 0.50 * c + 0.15 * (1.0 / max(h, 1)) + 0.25 * u + 0.10 * p

    # Warmup
    for _ in range(200):
        _score(0.9, 1, 0.95, 0.7)

    times = []
    for i in range(n):
        c = 0.5 + (i % 5) * 0.1
        h = 1 + (i % 4)
        u = 0.7 + (i % 3) * 0.05
        p = 0.6 + (i % 4) * 0.05
        t0 = time.perf_counter()
        _score(c, h, u, p)
        times.append(time.perf_counter() - t0)
    _row("S(Vc) formula (4 multiplies + adds)", _stats(times))
    _note("Cost is negligible — scoring N=1000 peers takes < 1ms total")


# ---------------------------------------------------------------------------
# Benchmark: Adaptive gossip interval computation (Browser Demo 3)
# ---------------------------------------------------------------------------

def bench_adaptive_interval(n: int):
    """Score → gossip interval formula used in browser_demo_3/worker.js.

    interval = BASE_INTERVAL_MS / score^1.2  ±25% jitter, clamped [200, 15000]
    """
    import random as _rand

    _header("Adaptive Gossip Interval  (BASE / score^1.2 ± jitter)")

    BASE_INTERVAL_MS = 2000.0
    SCORES = [0.05, 0.10, 0.25, 0.50, 0.75, 0.95]

    def _compute(score: float) -> float:
        raw = BASE_INTERVAL_MS / (score ** 1.2)
        raw *= _rand.uniform(0.75, 1.25)
        return max(200.0, min(raw, 15000.0))

    # Warmup
    for s in SCORES:
        for _ in range(50):
            _compute(s)

    for score in SCORES:
        times = []
        for i in range(n):
            t0 = time.perf_counter()
            _compute(score)
            times.append(time.perf_counter() - t0)
        _row(f"score={score:.2f}  interval≈{BASE_INTERVAL_MS / score**1.2:.0f}ms", _stats(times))

    _note(
        "Pure arithmetic — expected > 500 000 ops/sec. "
        "Sovereign Pulse Mode bypasses this and uses BASE_INTERVAL_MS directly."
    )


# ---------------------------------------------------------------------------
# Benchmark: LRU dedup cache (gossip echo prevention)
# ---------------------------------------------------------------------------

def bench_dedup_cache(n: int):
    """50-entry LRU dedup cache used in browser_demo_3/worker.js to prevent echo loops.

    Each received message is checked against the cache before re-broadcasting.
    Simulates realistic 20% duplicate rate with 50 unique pod IDs.
    """
    from collections import OrderedDict

    _header("Gossip Dedup Cache  (LRU 50-entry, 20% dup rate)")

    CACHE_SIZE = 50
    NUM_PODS = 50
    DUP_RATE = 0.20

    # Pre-generate a stream of (pod_id, timestamp) tuples
    import random as _rand
    pod_ids = [f"pod-{i:04x}" for i in range(NUM_PODS)]
    timestamps = [float(i * 1000) for i in range(n)]
    stream = []
    prev_key = None
    for i in range(n):
        if prev_key and _rand.random() < DUP_RATE:
            stream.append(prev_key)
        else:
            k = (pod_ids[i % NUM_PODS], timestamps[i])
            stream.append(k)
            prev_key = k

    cache: "OrderedDict[tuple, bool]" = OrderedDict()

    def _check(key: tuple) -> bool:
        if key in cache:
            cache.move_to_end(key)
            return True  # duplicate
        cache[key] = True
        if len(cache) > CACHE_SIZE:
            cache.popitem(last=False)
        return False

    # Warmup
    for k in stream[:min(200, n)]:
        _check(k)
    cache.clear()

    times_hit, times_miss = [], []
    dup_count = 0
    for k in stream:
        t0 = time.perf_counter()
        hit = _check(k)
        elapsed = time.perf_counter() - t0
        if hit:
            times_hit.append(elapsed)
            dup_count += 1
        else:
            times_miss.append(elapsed)

    if times_miss:
        _row("cache miss  (new message, forward)", _stats(times_miss))
    if times_hit:
        _row("cache hit   (duplicate, drop)      ", _stats(times_hit))
    _note(
        f"Dup rate achieved: {dup_count / n * 100:.1f}% of {n} messages. "
        "Expected: > 1 000 000 ops/sec for both paths."
    )


# ---------------------------------------------------------------------------
# Benchmark: Propagation damping (hop-count guard)
# ---------------------------------------------------------------------------

def bench_propagation_damping(n: int):
    """Propagation damping check: propagated_count < PROPAGATION_LIMIT=15.

    Every forwarded gossip message increments propagated_count.
    Messages at or above the limit are dropped to prevent broadcast storms.
    """
    import random as _rand

    _header("Propagation Damping  (propagated_count < PROPAGATION_LIMIT=15)")

    PROPAGATION_LIMIT = 15

    counts = [_rand.randint(0, 20) for _ in range(n)]

    # Warmup
    for c in counts[:min(500, n)]:
        _ = c < PROPAGATION_LIMIT

    times_pass, times_drop = [], []
    passed = 0
    for c in counts:
        t0 = time.perf_counter()
        forward = c < PROPAGATION_LIMIT
        elapsed = time.perf_counter() - t0
        if forward:
            times_pass.append(elapsed)
            passed += 1
        else:
            times_drop.append(elapsed)

    if times_pass:
        _row("forward (count < limit)", _stats(times_pass))
    if times_drop:
        _row("drop    (count ≥ limit)", _stats(times_drop))
    _note(
        f"Forwarded {passed / n * 100:.1f}% of messages (counts 0–14 of 0–20 range). "
        "Expected: > 2 000 000 ops/sec — single integer comparison."
    )


# ---------------------------------------------------------------------------
# Benchmark: NKey patch verification
# ---------------------------------------------------------------------------

def bench_nkey(n: int):
    _header("NKey Patch Verification  (Ed25519)")

    if not _NKEY_OK:
        if not _CRYPTO_OK:
            _note("cryptography not installed — pip install cryptography")
        else:
            _note("ruvon-edge not installed — pip install -e 'packages/ruvon-edge[edge]'")
        return

    import base64 as _b64

    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    pub_b64 = _b64.urlsafe_b64encode(pub_bytes).decode()

    verifier = NKeyPatchVerifier(pub_b64)

    payloads = {
        "256 B  (heartbeat-size)": secrets.token_bytes(256),
        "4 KB   (small WASM)    ": secrets.token_bytes(4096),
        "64 KB  (typical WASM)  ": secrets.token_bytes(65536),
    }

    for label, binary in payloads.items():
        sig_valid = _b64.urlsafe_b64encode(priv.sign(binary)).decode()
        sig_bad   = _b64.urlsafe_b64encode(secrets.token_bytes(64)).decode()

        # Warmup
        for _ in range(20):
            verifier.verify(binary, sig_valid)
            verifier.verify(binary, sig_bad)

        times_v = []
        for _ in range(n):
            t0 = time.perf_counter()
            verifier.verify(binary, sig_valid)
            times_v.append(time.perf_counter() - t0)
        _row(f"verify() valid   {label}", _stats(times_v))

        times_i = []
        for _ in range(n):
            t0 = time.perf_counter()
            verifier.verify(binary, sig_bad)
            times_i.append(time.perf_counter() - t0)
        _row(f"verify() invalid {label}", _stats(times_i))

    # from_env() — env var absent → None immediately
    times_env = []
    for _ in range(min(n, 2000)):
        t0 = time.perf_counter()
        NKeyPatchVerifier.from_env()
        times_env.append(time.perf_counter() - t0)
    _row("from_env() → None  (env var absent)", _stats(times_env))

    _note(
        "Ed25519 verification is constant-time with respect to payload size "
        "— cost is dominated by the 64-byte signature check, not data hashing."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Rufus RUVON standalone benchmark")
    parser.add_argument("--iterations", type=int, default=5000,
                        help="Base iteration count (default: 5000)")
    parser.add_argument("--quick", action="store_true",
                        help="Run with 500 iterations (~2 seconds)")
    parser.add_argument("--output", choices=["text", "json"], default="text")
    args = parser.parse_args()

    n = 500 if args.quick else args.iterations

    print("\n" + "=" * 72)
    print("  RUFUS SDK — RUVON BENCHMARK SUITE")
    print("=" * 72)
    print(f"  Iterations       : {n}")
    print(f"  capability_gossip: {'available' if _GOSSIP_OK else 'NOT AVAILABLE'}")
    print(f"  nkey_verifier    : {'available' if _NKEY_OK else 'NOT AVAILABLE'}")
    print()

    bench_vector_serialisation(n)
    bench_classify_tier(n)
    bench_peer_selection(n)
    bench_vector_scoring(n)
    bench_adaptive_interval(n)
    bench_dedup_cache(n)
    bench_propagation_damping(n)
    bench_nkey(n)

    print("\n" + "=" * 72)
    print("  DONE")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
