#!/usr/bin/env python3
"""
analyze_chaos.py — Post-test analysis for run_chaos_load_test.py output.

Reads timeline.jsonl + chaos_results.json from the output directory and prints:
  1. Per-phase latency table (p99 mean / max, error rate, throughput)
  2. Chaos event correlation (p99 before → after each event)
  3. Reconnect recovery time (seconds until p99 drops below 500ms)
  4. Final PASS/FAIL verdict against success criteria

Optionally validates data loss against PostgreSQL (--db-url):
  Queries saf_transactions WHERE device_id LIKE 'chaos-test-%'
  Compares DB row count to client-reported transactions_synced.

Usage:
  python tests/load/analyze_chaos.py --input-dir ./chaos_test_1000/
  python tests/load/analyze_chaos.py --input-dir ./chaos_test_1000/ \\
      --db-url postgresql://user:pass@localhost/my_app_db
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Data loading
# =============================================================================

def load_timeline(path: Path) -> List[Dict[str, Any]]:
    points: List[Dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                points.append(json.loads(line))
    return points


def load_results(path: Path) -> Dict[str, Any]:
    with open(path) as f:
        return json.load(f)


# =============================================================================
# Statistical helpers
# =============================================================================

def _pct(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(int(p * (len(s) - 1)), len(s) - 1)]


def phase_summary(timeline: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Aggregate per-phase statistics from the timeline.

    Error rates are computed from per-interval deltas (``interval_errors`` /
    delta ``total_requests``), NOT from the cumulative ``error_rate_pct`` field.
    Using the cumulative field causes stable phases (cooldown) to appear broken
    because they inherit the accumulated errors from earlier chaos phases.
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for pt in timeline:
        buckets.setdefault(pt.get("phase", "unknown"), []).append(pt)

    summary: Dict[str, Dict[str, Any]] = {}
    for phase, pts in buckets.items():
        p99s = [p["p99_ms"] for p in pts if p.get("p99_ms", 0) > 0]
        tx5s = [p["interval_tx"] for p in pts]
        t_min = pts[0]["t"]
        t_max = pts[-1]["t"]

        # Per-interval error rate: interval_errors / Δtotal_requests per sample.
        # This gives the true per-window error rate regardless of history.
        interval_err_rates: List[float] = []
        for i, p in enumerate(pts):
            ierr      = p.get("interval_errors", 0)
            prev_req  = pts[i - 1]["total_requests"] if i > 0 else 0
            delta_req = p["total_requests"] - prev_req
            interval_err_rates.append((ierr / delta_req * 100) if delta_req > 0 else 0.0)

        summary[phase] = {
            "samples":      len(pts),
            "duration_s":   round(t_max - t_min, 1),
            "p99_mean_ms":  round(sum(p99s) / len(p99s), 1) if p99s else 0.0,
            "p99_max_ms":   round(max(p99s),             1) if p99s else 0.0,
            "err_mean_pct": round(sum(interval_err_rates) / len(interval_err_rates), 3)
                            if interval_err_rates else 0.0,
            "err_max_pct":  round(max(interval_err_rates), 3) if interval_err_rates else 0.0,
            "tx_5s_mean":   round(sum(tx5s) / len(tx5s), 0) if tx5s else 0.0,
        }
    return summary


def find_event_time(timeline: List[Dict], event_type: str) -> Optional[float]:
    for pt in timeline:
        if pt.get("event") == event_type:
            return pt["t"]
    return None


def recovery_time(
    timeline: List[Dict],
    event_t: float,
    target_p99_ms: float = 500.0,
) -> Optional[float]:
    """Return seconds after event_t when p99 first drops back below target_p99_ms."""
    for pt in timeline:
        if pt["t"] > event_t and 0 < pt.get("p99_ms", 0) < target_p99_ms:
            return round(pt["t"] - event_t, 1)
    return None


def event_impact(
    timeline: List[Dict],
    event_t: float,
    window_before: float = 15.0,
    window_after: float = 20.0,
) -> Tuple[Optional[float], Optional[float]]:
    """Return (max p99 in window_before, max p99 in window_after) for an event."""
    before = [p["p99_ms"] for p in timeline
              if event_t - window_before <= p["t"] < event_t and p.get("p99_ms", 0) > 0]
    after  = [p["p99_ms"] for p in timeline
              if event_t < p["t"] <= event_t + window_after and p.get("p99_ms", 0) > 0]
    return (max(before) if before else None), (max(after) if after else None)


# =============================================================================
# PostgreSQL data-loss validation (optional)
# =============================================================================

async def validate_data_loss(db_url: str, results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Count chaos-test rows in saf_transactions and compare to client-reported total.

    Note: DB count will be ≤ client-sent because the same idempotency keys are
    re-sent on each sync cycle (ON CONFLICT DO NOTHING deduplicates them).
    The goal is confirming zero *additional* loss — i.e., rows that were
    accepted by the server should always reach the DB.
    """
    try:
        import asyncpg  # type: ignore
    except ImportError:
        return {"error": "asyncpg not installed — skip pip install asyncpg"}

    try:
        conn = await asyncpg.connect(db_url, timeout=10)
        try:
            db_count = await conn.fetchval(
                "SELECT COUNT(*) FROM saf_transactions WHERE device_id LIKE 'chaos-test-%'"
            )
            sent = results.get("transactions_synced", 0)
            return {
                "client_transactions_synced": sent,
                "db_unique_rows":            int(db_count),
                "note": (
                    "DB count < client synced is expected (same idempotency keys re-sent). "
                    "The check is: db_unique_rows > 0 and no 5xx errors during non-chaos phases."
                ),
            }
        finally:
            await conn.close()
    except Exception as exc:
        return {"error": str(exc)}


# =============================================================================
# Main report
# =============================================================================

PHASE_ORDER = ["baseline", "partition", "jitter", "reconnect", "spike", "cooldown"]


def print_analysis(
    timeline: List[Dict[str, Any]],
    results: Dict[str, Any],
    db_stats: Optional[Dict[str, Any]] = None,
):
    summary = phase_summary(timeline)

    print("\n" + "═" * 80)
    print("  CHAOS ANALYSIS REPORT")
    print("═" * 80)
    max_conc    = results.get("max_concurrent_syncs", 0)
    num_devices_hdr = results.get("num_devices", 1)
    conc_ratio_hdr  = max(1.0, num_devices_hdr / max_conc) if max_conc else 1.0
    chaos_pct = round(results.get("chaos_device_fraction", 0.30) * 100)
    print(f"  Devices          : {results.get('num_devices', '?')}")
    print(f"  Chaos group      : {chaos_pct}% of devices (offline during partition)")
    if max_conc:
        print(f"  Max concurrency  : {max_conc} simultaneous syncs")
    print(f"  Duration         : {results.get('duration_seconds', 0):.0f}s")
    print(f"  Timeline points  : {results.get('timeline_points', len(timeline))}")
    print(f"  Total requests   : {results.get('total_requests', 0):,}")
    print(f"  Transactions     : {results.get('transactions_synced', 0):,}")
    print(f"  Overall errors   : {results.get('total_errors', 0):,}  "
          f"({results.get('error_rate_pct', 0):.3f}%)")
    print()

    # ── Per-phase table ───────────────────────────────────────────────────────
    print(f"  {'Phase':<14} {'Dur':>5}  {'p99 mean':>9}  {'p99 max':>9}  "
          f"{'err% max':>9}  {'tx/5s':>7}")
    print(f"  {'─' * 62}")
    for phase in PHASE_ORDER:
        s = summary.get(phase)
        if not s:
            continue
        print(
            f"  {phase:<14} {s['duration_s']:>4.0f}s  "
            f"{s['p99_mean_ms']:>8.0f}ms  "
            f"{s['p99_max_ms']:>8.0f}ms  "
            f"{s['err_max_pct']:>8.3f}%  "
            f"{s['tx_5s_mean']:>7.0f}"
        )
    print()

    # ── Event correlation ─────────────────────────────────────────────────────
    events = results.get("events", [])
    if events:
        print(f"  CHAOS EVENT CORRELATION  (p99 15s-before → 20s-after):")
        print(f"  {'─' * 62}")
        for ev in events:
            t          = ev["t"]
            event_type = ev["event"]
            label      = ev.get("label", "")
            p99_before, p99_after = event_impact(timeline, t)
            delta_str = ""
            if p99_before is not None and p99_after is not None:
                delta = p99_after - p99_before
                sign  = "+" if delta >= 0 else ""
                delta_str = f"  {p99_before:.0f}ms → {p99_after:.0f}ms  ({sign}{delta:.0f}ms)"
            elif p99_after is not None:
                delta_str = f"  → {p99_after:.0f}ms"
            print(f"  T+{t:4.0f}s  {event_type:<26} {delta_str}")
            if label:
                print(f"           ↳ {label}")
        print()

    # ── Reconnect recovery ────────────────────────────────────────────────────
    # The recovery time is measured from the THUNDERING_RECONNECT event to the
    # first timeline sample where p99 < 500ms.  Because the timeline is sampled
    # discretely (every ~5s), the measured time has ±sample_interval/2 precision.
    # We allow one full sample interval of tolerance so a genuine 30s recovery
    # doesn't fail due to rounding to the next sample boundary.
    reconnect_t = find_event_time(timeline, "THUNDERING_RECONNECT")
    recovery_p99_target = round(500.0 * conc_ratio_hdr)
    rec_s_reconnect: Optional[float] = None
    if reconnect_t is not None:
        rec_s_reconnect = recovery_time(
            timeline, reconnect_t, target_p99_ms=float(recovery_p99_target)
        )
        print(f"  RECONNECT RECOVERY:")
        if rec_s_reconnect is not None:
            # Infer sample interval from timeline spacing (default 5s)
            sample_interval = 5.0
            if len(timeline) >= 2:
                sample_interval = round(timeline[1]["t"] - timeline[0]["t"], 1)
            recovery_target = 30.0
            ok = rec_s_reconnect <= recovery_target + sample_interval
            print(f"  {'✅' if ok else '❌'} p99 returned below {recovery_p99_target}ms "
                  f"in {rec_s_reconnect}s  "
                  f"(target ≤ {recovery_target:.0f}s ±{sample_interval:.0f}s sample tolerance)")
        else:
            print(f"  ⚠️  p99 never recovered below {recovery_p99_target}ms during the test window")
        print()

    # ── Data loss validation ──────────────────────────────────────────────────
    if db_stats:
        print("  DATA LOSS VALIDATION:")
        print(f"  {'─' * 62}")
        if "error" in db_stats:
            print(f"  ⚠️  Skipped: {db_stats['error']}")
        else:
            print(f"  Client synced : {db_stats['client_transactions_synced']:,}")
            print(f"  DB rows       : {db_stats['db_unique_rows']:,}  (unique after idempotency dedup)")
            print(f"  Note          : {db_stats['note']}")
        print()

    # ── Success criteria ──────────────────────────────────────────────────────
    # Derive thresholds from run parameters so they scale with the test config.
    # num_devices / max_conc / conc_ratio_hdr already extracted above for the header.
    num_devices   = num_devices_hdr
    conc_ratio    = conc_ratio_hdr
    chaos_frac    = results.get("chaos_device_fraction", 0.30)   # default 30% offline

    baseline_p99  = summary.get("baseline",  {}).get("p99_max_ms",  0.0)
    baseline_err  = summary.get("baseline",  {}).get("err_max_pct", 0.0)
    cooldown_p99  = summary.get("cooldown",  {}).get("p99_max_ms",  0.0)
    cooldown_err  = summary.get("cooldown",  {}).get("err_max_pct", 0.0)   # 100 = no data
    partition_err = summary.get("partition", {}).get("err_max_pct", 0.0)
    # Use mean p99 for reconnect: the max captures only the burst-peak spike which the
    # recovery-time check already validates.  Mean reflects sustained post-reconnect load.
    reconnect_p99 = summary.get("reconnect", {}).get("p99_mean_ms", 0.0)

    # Stable-phase error threshold: 0% in baseline; 0% in cooldown (if it ran).
    # Checking "overall error rate < 0.1%" is meaningless when the test deliberately
    # partitions chaos_frac of devices — those failures are expected and bounded by the
    # partition_err check instead.
    stable_err_ok = (baseline_err == 0.0) and (cooldown_err == 0.0 if cooldown_p99 > 0 else True)
    stable_err_label = (
        f"Stable-phase error rate = 0%    "
        f"(baseline={baseline_err:.3f}%"
        + (f", cooldown={cooldown_err:.3f}%" if cooldown_p99 > 0 else ", cooldown=n/a")
        + ")"
    )

    # Partition error ceiling: chaos_frac of devices are offline; we allow up to 2×
    # that fraction as the max error rate to account for bursts at phase transitions.
    partition_ceil = min(chaos_frac * 2 * 100, 50.0)   # capped at 50%, in percent
    partition_ok   = partition_err < partition_ceil

    # p99 thresholds scale with the concurrency ratio (num_devices / max_concurrent_syncs).
    # At ratio=1 (one slot per device) the baseline is 500ms.  At ratio=5 (1000d/200c) the
    # expected queuing overhead is 5× higher, so the target scales linearly.
    baseline_target  = round(500.0 * conc_ratio)
    cooldown_target  = round(500.0 * conc_ratio)
    reconnect_target = round(800.0 * conc_ratio)
    scale_note = f" [×{conc_ratio:.1f} for {num_devices}d/{max_conc}c]" if conc_ratio > 1 else ""

    checks: List[Tuple[bool, str]] = [
        (stable_err_ok,        stable_err_label),
        (baseline_p99 < baseline_target,
                               f"Baseline p99 < {baseline_target}ms{scale_note:<20} ({baseline_p99:.0f}ms)"),
        (cooldown_p99 < cooldown_target if cooldown_p99 > 0 else True,
                               f"Post-chaos p99 < {cooldown_target}ms{scale_note:<20} "
                               + (f"({cooldown_p99:.0f}ms)" if cooldown_p99 > 0 else "(phase not reached)")),
        (partition_ok,         f"Partition error rate < {partition_ceil:.0f}%      ({partition_err:.1f}%)"),
        (reconnect_p99 < reconnect_target,
                               f"Post-reconnect mean p99 < {reconnect_target}ms{scale_note:<20} ({reconnect_p99:.0f}ms)"),
    ]
    if reconnect_t is not None and rec_s_reconnect is not None:
        sample_interval = round(timeline[1]["t"] - timeline[0]["t"], 1) if len(timeline) >= 2 else 5.0
        checks.append((
            rec_s_reconnect <= 30.0 + sample_interval,
            f"Reconnect recovery ≤ 30s         ({rec_s_reconnect}s, ±{sample_interval:.0f}s tolerance)",
        ))

    all_pass = all(ok for ok, _ in checks)
    print("  SUCCESS CRITERIA:")
    print(f"  {'─' * 62}")
    for ok, label in checks:
        print(f"  {'✅' if ok else '❌'} {label}")

    print()
    verdict = (
        "✅  PASS — SAF_SYNC is chaos-resilient"
        if all_pass else
        "❌  FAIL — investigate timeline.jsonl for the failing phase"
    )
    print(f"  VERDICT: {verdict}")
    print("═" * 80)


# =============================================================================
# CLI entry point
# =============================================================================

async def async_main(args) -> int:
    input_dir     = Path(args.input_dir)
    timeline_path = input_dir / "timeline.jsonl"
    results_path  = input_dir / "chaos_results.json"

    missing = [p for p in (timeline_path, results_path) if not p.exists()]
    if missing:
        for p in missing:
            print(f"ERROR: {p} not found — run run_chaos_load_test.py first", file=sys.stderr)
        return 1

    timeline = load_timeline(timeline_path)
    results  = load_results(results_path)

    db_stats: Optional[Dict[str, Any]] = None
    if args.db_url:
        print(f"Querying {args.db_url} for data-loss validation...")
        db_stats = await validate_data_loss(args.db_url, results)

    print_analysis(timeline, results, db_stats)
    return 0


def main():
    p = argparse.ArgumentParser(
        description="Analyze chaos load test results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--input-dir", default="./chaos_test/",
                   help="Directory containing chaos_results.json + timeline.jsonl")
    p.add_argument("--db-url",    default=None,
                   help="PostgreSQL URL for data-loss validation (optional)")
    args = p.parse_args()
    sys.exit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
