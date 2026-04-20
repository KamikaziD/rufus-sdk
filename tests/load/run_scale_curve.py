#!/usr/bin/env python3
"""
run_scale_curve.py — Scale-out curve runner for Ruvon load test suite.

Runs a chosen scenario at increasing device counts (N) and writes a unified
JSON file with throughput / p50 / p95 / p99 / error-rate per data point.

The output lets you detect O(N²) gossip fanout or pool-exhaustion cliffs
before they hit production.

Supported scenarios
-------------------
  saf_sync          — HTTP, requires server registration
  ruvon_gossip      — local-only (no HTTP, no registration)
  heartbeat         — HTTP, requires server registration
  election_stability — local-only
  payload_variance  — local-only
  e2e_decision      — local-only

Usage
-----
  # HTTP scenario (needs a running server):
  python tests/load/run_scale_curve.py \\
      --scenario saf_sync \\
      --ns 10,100,500,1000,2000 \\
      --duration 120 \\
      --cloud-url http://localhost:8000 \\
      --output-dir ./scale_curve/

  # Local-only scenario (no server needed):
  python tests/load/run_scale_curve.py \\
      --scenario ruvon_gossip \\
      --ns 10,100,500,1000 \\
      --duration 60 \\
      --output-dir ./scale_curve/

Output
------
  <output-dir>/scale_curve.json   — full data (one entry per N)
  <output-dir>/scale_curve.txt    — human-readable table

JSON schema per entry:
  {
    "n":              int,
    "scenario":       str,
    "duration_s":     float,
    "req_s":          float,      # 0 for local-only scenarios
    "p50_ms":         float,
    "p95_ms":         float,
    "p99_ms":         float,
    "error_rate_pct": float,
    "extra":          dict        # scenario-specific counters
  }
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── path bootstrap ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT / "tests" / "load") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "tests" / "load"))

from orchestrator import LoadTestOrchestrator, LoadTestResults  # noqa: E402

logger = logging.getLogger("scale_curve")

# Scenarios that don't need HTTP or server registration.
_LOCAL_ONLY = frozenset(
    ("ruvon_gossip", "nkey_patch", "wasm_thundering_herd",
     "election_stability", "payload_variance", "e2e_decision")
)


# =============================================================================
# Result extraction
# =============================================================================

def _pct(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(int(p * (len(s) - 1)), len(s) - 1)] * 1000  # → ms


def extract_point(n: int, scenario: str, results: LoadTestResults) -> Dict[str, Any]:
    """Convert a LoadTestResults into a single scale-curve data point."""
    req_s = results.total_requests / results.duration_seconds if results.duration_seconds > 0 else 0.0

    # Pick the right latency list depending on scenario
    if scenario in ("election_stability",) and results.election_latencies:
        lats = results.election_latencies
    elif scenario in ("payload_variance",) and results.payload_latencies:
        # Flatten all size buckets for the aggregate curve
        lats = [lat for bucket in results.payload_latencies.values() for lat in bucket]
    elif scenario in ("e2e_decision",) and results.e2e_decision_latencies:
        lats = results.e2e_decision_latencies
    elif scenario in ("ruvon_gossip",) and results.gossip_broadcast_latencies:
        lats = results.gossip_broadcast_latencies
    else:
        lats = results.request_latencies  # HTTP latencies (seconds)

    extra: Dict[str, Any] = {}
    if results.transactions_synced:
        extra["transactions_synced"] = results.transactions_synced
        extra["tx_s"] = round(results.transactions_synced / results.duration_seconds, 1) \
            if results.duration_seconds > 0 else 0.0
    if results.gossip_broadcasts:
        extra["gossip_broadcasts"] = results.gossip_broadcasts
    if results.elections_run:
        extra["elections_run"] = results.elections_run
        extra["flap_count"] = results.flap_count
    if results.e2e_ack_count:
        extra["e2e_ack_count"] = results.e2e_ack_count
    if results.payload_latencies:
        # per-bucket p95 for payload_variance
        extra["bucket_p95_ms"] = {
            label: round(_pct(lats_b, 0.95), 3)
            for label, lats_b in sorted(results.payload_latencies.items())
        }

    return {
        "n":              n,
        "scenario":       scenario,
        "duration_s":     round(results.duration_seconds, 1),
        "req_s":          round(req_s, 1),
        "p50_ms":         round(_pct(lats, 0.50), 3),
        "p95_ms":         round(_pct(lats, 0.95), 3),
        "p99_ms":         round(_pct(lats, 0.99), 3),
        "error_rate_pct": round(results.error_rate, 4),
        "extra":          extra,
    }


# =============================================================================
# Single-N runner
# =============================================================================

async def run_one(
    n: int,
    scenario: str,
    duration_seconds: int,
    cloud_url: str,
) -> LoadTestResults:
    """Spin up N devices, run the scenario for duration_seconds, return results."""
    is_local = scenario in _LOCAL_ONLY
    orchestrator = LoadTestOrchestrator(
        cloud_url=cloud_url,
        base_api_key="scale_curve_key",
    )
    await orchestrator.setup_devices(
        n,
        cleanup_first=not is_local,
        register_with_server=not is_local,
    )
    results = await orchestrator.run_scenario(
        scenario=scenario,
        duration_seconds=duration_seconds,
        skip_device_setup=True,
    )
    # Teardown (best-effort)
    try:
        await asyncio.gather(*[d.close() for d in orchestrator._devices])
    except Exception:
        pass
    return results


# =============================================================================
# Report printing
# =============================================================================

def print_table(points: List[Dict[str, Any]]) -> None:
    print()
    print(f"  {'N':>6}  {'p50':>8}  {'p95':>8}  {'p99':>8}  {'err%':>7}  {'req/s':>7}")
    print("  " + "─" * 54)
    for pt in points:
        print(
            f"  {pt['n']:>6}  "
            f"{pt['p50_ms']:>7.2f}ms  "
            f"{pt['p95_ms']:>7.2f}ms  "
            f"{pt['p99_ms']:>7.2f}ms  "
            f"{pt['error_rate_pct']:>6.3f}%  "
            f"{pt['req_s']:>7.1f}"
        )
    print()

    # Cliff detection: flag if p99 grows faster than 2× for each 10× N increase
    if len(points) >= 2:
        for i in range(1, len(points)):
            prev, cur = points[i - 1], points[i]
            n_ratio = cur["n"] / prev["n"] if prev["n"] else 1
            p99_ratio = cur["p99_ms"] / prev["p99_ms"] if prev["p99_ms"] > 0 else 0
            if p99_ratio > n_ratio * 2:
                print(
                    f"  ⚠️  p99 cliff detected between N={prev['n']} → N={cur['n']}: "
                    f"p99 grew {p99_ratio:.1f}× for {n_ratio:.1f}× N increase"
                )


# =============================================================================
# Main
# =============================================================================

async def async_main(args) -> int:
    ns: List[int] = [int(x.strip()) for x in args.ns.split(",")]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "scale_curve.json"
    txt_path  = output_dir / "scale_curve.txt"

    print(f"\nScale-curve: scenario={args.scenario}  N={ns}  duration={args.duration}s")
    print(f"Output dir:  {output_dir.resolve()}\n")

    points: List[Dict[str, Any]] = []

    for n in ns:
        logger.info(f"Running N={n} …")
        t0 = time.monotonic()
        try:
            results = await run_one(
                n=n,
                scenario=args.scenario,
                duration_seconds=args.duration,
                cloud_url=args.cloud_url,
            )
            pt = extract_point(n, args.scenario, results)
        except Exception as exc:
            logger.error(f"N={n} failed: {exc}")
            pt = {
                "n": n, "scenario": args.scenario, "duration_s": 0,
                "req_s": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0,
                "error_rate_pct": 100.0, "extra": {"error": str(exc)},
            }
        elapsed = time.monotonic() - t0
        points.append(pt)
        print(
            f"  N={n:<6}  p50={pt['p50_ms']:.2f}ms  p95={pt['p95_ms']:.2f}ms  "
            f"p99={pt['p99_ms']:.2f}ms  err={pt['error_rate_pct']:.3f}%  "
            f"({elapsed:.0f}s wall)"
        )

        # Brief cooldown between runs to let the server / event loop drain
        if n != ns[-1]:
            await asyncio.sleep(5)

    # ── Write JSON ─────────────────────────────────────────────────────────────
    with open(json_path, "w") as f:
        json.dump(
            {"scenario": args.scenario, "ns": ns, "duration_s": args.duration, "points": points},
            f,
            indent=2,
        )
    logger.info(f"JSON written to {json_path}")

    # ── Write text table ────────────────────────────────────────────────────────
    import io
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    print(f"Scale curve — {args.scenario}  (duration={args.duration}s per run)")
    print_table(points)
    sys.stdout = old_stdout
    table_str = buf.getvalue()
    txt_path.write_text(table_str)
    print(table_str)

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Ruvon scale-out curve runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--scenario",
        default="saf_sync",
        choices=[
            "saf_sync", "ruvon_gossip", "heartbeat",
            "election_stability", "payload_variance", "e2e_decision",
            "nkey_patch",
        ],
        help="Scenario to sweep (default: saf_sync)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="run_all",
        help="Run all local-only scenarios sequentially "
             "(ruvon_gossip, election_stability, payload_variance, e2e_decision, nkey_patch). "
             "Each gets its own <scenario>_scale_curve.json/.txt in --output-dir.",
    )
    parser.add_argument(
        "--ns",
        default="10,100,500,1000,2000",
        help="Comma-separated device counts (default: 10,100,500,1000,2000)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=120,
        help="Duration per run in seconds (default: 120)",
    )
    parser.add_argument(
        "--cloud-url",
        default=os.getenv("RUVON_CLOUD_URL", "http://localhost:8000"),
        help="Cloud control-plane URL (default: RUVON_CLOUD_URL or http://localhost:8000)",
    )
    parser.add_argument(
        "--output-dir",
        default="./scale_curve/",
        help="Directory to write scale_curve.json + scale_curve.txt (default: ./scale_curve/)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.run_all:
        _ALL_LOCAL = [
            "ruvon_gossip", "election_stability", "payload_variance",
            "e2e_decision", "nkey_patch",
        ]
        output_dir = Path(args.output_dir)
        rc = 0
        for scenario in _ALL_LOCAL:
            import copy
            scenario_args = copy.copy(args)
            scenario_args.scenario = scenario
            scenario_args.output_dir = str(output_dir / scenario)
            print(f"\n{'='*60}")
            print(f"  SCENARIO: {scenario}")
            print(f"{'='*60}")
            ret = asyncio.run(async_main(scenario_args))
            if ret != 0:
                rc = ret
        sys.exit(rc)

    sys.exit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
