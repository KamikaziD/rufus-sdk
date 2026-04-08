#!/usr/bin/env python3
"""
Rufus Load Test Runner.

Command-line interface for running load tests against Ruvon Edge control plane.

Usage:
    python run_load_test.py --scenario heartbeat --devices 1000 --duration 600
    python run_load_test.py --scenario saf_sync --devices 500
    python run_load_test.py --all --devices 100
"""

import argparse
import asyncio
import logging
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load .env file if it exists
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

try:
    from tests.load.orchestrator import LoadTestOrchestrator, ScenarioRunner, LoadTestResults
except ModuleNotFoundError:
    from orchestrator import LoadTestOrchestrator, ScenarioRunner, LoadTestResults  # type: ignore[no-redef]

# Configure logging: INFO to file, WARNING-only to console (suppress httpx per-request noise)
_file_handler = logging.FileHandler('load_test.log')
_file_handler.setLevel(logging.INFO)
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[_console_handler, _file_handler]
)

# Suppress per-request httpx/httpcore noise from console
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def progress_callback(progress: dict):
    """Print progress updates."""
    print(
        f"Progress: {progress['progress_percent']:.1f}% | "
        f"Requests: {progress['total_requests']} | "
        f"Errors: {progress['total_errors']} | "
        f"Rate: {progress['requests_per_second']:.1f} req/s"
    )


async def ensure_seed_data(db_url: str):
    """
    Ensure database has seed data before running load tests.

    Runs seed_data.py to populate database with demo workflows and edge devices.
    The script is idempotent (uses ON CONFLICT DO NOTHING), so running it multiple
    times is safe and won't create duplicates.

    Args:
        db_url: Database connection URL (e.g., postgresql://user:pass@host/db)
    """
    logger.info("Ensuring seed data exists in database...")

    # Check if seed_data.py exists
    project_root = Path(__file__).parent.parent.parent
    seed_script = project_root / "tools" / "seed_data.py"

    if not seed_script.exists():
        logger.warning(f"Seed script not found at {seed_script}, skipping seed check")
        return

    try:
        # Run seed_data.py (idempotent - won't create duplicates)
        result = subprocess.run(
            [
                sys.executable,
                str(seed_script),
                "--db-url", db_url,
                "--type", "all"
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True
        )

        # Log output for debugging
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    logger.debug(line)

        logger.info(f"✓ Seed data verified (idempotent operation)")

    except subprocess.TimeoutExpired:
        logger.error("Seed data operation timed out after 60 seconds")
        raise
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to seed database: {e}")
        if e.stdout:
            logger.error(f"Output: {e.stdout}")
        if e.stderr:
            logger.error(f"Error: {e.stderr}")
        raise
    except Exception as e:
        logger.warning(f"Seed data check failed: {e}, continuing anyway...")


def print_results(results: LoadTestResults, workers: int = 1):
    """Print formatted test results."""
    print("\n" + "=" * 80)
    print(f"LOAD TEST RESULTS - {results.scenario.upper()}")
    print("=" * 80)
    print(f"Devices:              {results.num_devices}")
    print(f"Duration:             {results.duration_seconds:.1f}s")

    # For pure-local WASM scenarios there are no HTTP requests; show WASM steps/sec instead.
    _is_wasm_local = results.scenario in ("wasm_thundering_herd",)
    if _is_wasm_local:
        wasm_tps = results.wasm_steps_executed / results.duration_seconds if results.duration_seconds > 0 else 0
        total_wasm = results.wasm_steps_executed + results.wasm_step_failures
        wasm_err_rate = results.wasm_step_failures / total_wasm * 100 if total_wasm else 0
        print(f"WASM Steps Total:     {total_wasm:,}")
        print(f"WASM Step Failures:   {results.wasm_step_failures:,}")
        print(f"Error Rate:           {wasm_err_rate:.2f}%")
        print(f"Success Rate:         {100 - wasm_err_rate:.2f}%")
        print(f"Throughput:           {wasm_tps:.1f} steps/sec")
    else:
        print(f"Total Requests:       {results.total_requests:,}")
        print(f"Total Errors:         {results.total_errors:,}")
        print(f"Error Rate:           {results.error_rate:.2f}%")
        print(f"Success Rate:         {100 - results.error_rate:.2f}%")
        print(f"Throughput:           {results.requests_per_second:.1f} req/sec")
    print()

    if results.heartbeats_sent > 0:
        print(f"Heartbeats Sent:      {results.heartbeats_sent:,}")
        print(f"Heartbeat Failures:   {results.heartbeat_failures:,}")

    if results.transactions_synced > 0:
        print(f"Transactions Synced:  {results.transactions_synced:,}")
        print(f"Sync Failures:        {results.sync_failures:,}")

    if results.configs_downloaded > 0:
        print(f"Configs Downloaded:   {results.configs_downloaded:,}")
        print(f"Config Failures:      {results.config_failures:,}")

    if results.commands_received > 0:
        print(f"Commands Received:    {results.commands_received:,}")

    if results.wasm_steps_executed > 0 or results.wasm_step_failures > 0:
        total_wasm = results.wasm_steps_executed + results.wasm_step_failures
        wasm_success_rate = results.wasm_steps_executed / total_wasm * 100 if total_wasm else 0
        print(f"WASM Steps Executed:  {results.wasm_steps_executed:,}")
        print(f"WASM Step Failures:   {results.wasm_step_failures:,}")
        print(f"WASM Success Rate:    {wasm_success_rate:.2f}%")
        if results.wasm_execution_latencies:
            wl = sorted(results.wasm_execution_latencies)
            p50_wasm = wl[int(0.50 * (len(wl) - 1))] * 1000
            p95_wasm = wl[int(0.95 * (len(wl) - 1))] * 1000
            p99_wasm = wl[int(0.99 * (len(wl) - 1))] * 1000
            print(f"WASM Exec p50:        {p50_wasm:.0f}ms")
            print(f"WASM Exec p95:        {p95_wasm:.0f}ms")
            print(f"WASM Exec p99:        {p99_wasm:.0f}ms")

    # Error breakdown
    if results.total_errors > 0:
        print()
        print(f"Error Breakdown:")
        if results.errors_5xx > 0:
            pct = results.errors_5xx / results.total_requests * 100 if results.total_requests else 0
            print(f"  5xx (server):       {results.errors_5xx:,}  ({pct:.1f}%)  ← pool exhaustion / crash")
        if results.errors_4xx > 0:
            pct = results.errors_4xx / results.total_requests * 100 if results.total_requests else 0
            print(f"  4xx (client):       {results.errors_4xx:,}  ({pct:.1f}%)")
        if results.errors_timeout > 0:
            pct = results.errors_timeout / results.total_requests * 100 if results.total_requests else 0
            print(f"  Timeout:            {results.errors_timeout:,}  ({pct:.1f}%)")

    # Latency percentiles
    if results.request_latencies:
        p50 = results.latency_percentile(0.50)
        p95 = results.latency_percentile(0.95)
        p99 = results.latency_percentile(0.99)
        p_max = max(results.request_latencies) * 1000
        print()
        print(f"Latency p50:          {p50:.1f}ms")
        print(f"Latency p95:          {p95:.1f}ms")
        print(f"Latency p99:          {p99:.1f}ms")
        print(f"Latency max:          {p_max:.1f}ms")
        print(f"Latency samples:      {len(results.request_latencies):,}")

    print("=" * 80)

    # Check against targets
    print("\nPERFORMANCE TARGETS:")
    print("=" * 80)

    # Error rate target: < 1%  (skip for pure-local WASM — no HTTP requests)
    if results.scenario not in ("wasm_thundering_herd",):
        error_pass = results.error_rate < 1.0
        print(f"Error Rate < 1%:      {'✅ PASS' if error_pass else '❌ FAIL'} ({results.error_rate:.2f}%)")

    # Latency target: p95 < 500ms / p99 < 1000ms (not applicable to thundering_herd)
    if results.request_latencies and results.scenario != "thundering_herd":
        p95 = results.latency_percentile(0.95)
        latency_pass = p95 < 500.0
        print(f"Latency p95 < 500ms:  {'✅ PASS' if latency_pass else '❌ FAIL'} ({p95:.1f}ms)")

        p99 = results.latency_percentile(0.99)
        p99_pass = p99 < 1000.0
        print(f"Latency p99 < 1000ms: {'✅ PASS' if p99_pass else '❌ FAIL'} ({p99:.1f}ms)")

    # Throughput target (scenario-specific)
    if results.scenario == "heartbeat":
        # Target scales with device count: one heartbeat per device every 30s.
        # Wall-clock duration includes the stagger ramp-up window (up to heartbeat_interval
        # seconds before the first device fires), so exclude it from the denominator.
        heartbeat_interval = 30  # seconds — matches DeviceConfig default
        throughput_target = results.num_devices / heartbeat_interval
        effective_duration = max(results.duration_seconds - heartbeat_interval, 1)
        effective_rps = results.total_requests / effective_duration
        throughput_pass = effective_rps >= throughput_target * 0.9
        print(f"Throughput >= {throughput_target:.1f} req/s:  {'✅ PASS' if throughput_pass else '❌ FAIL'} ({effective_rps:.1f} req/s)")

    elif results.scenario == "saf_sync":
        # Target: 1000 tx/sec
        tx_per_sec = results.transactions_synced / results.duration_seconds if results.duration_seconds > 0 else 0
        throughput_target = 1000
        throughput_pass = tx_per_sec >= throughput_target * 0.9
        print(f"Transaction Rate >= {throughput_target} tx/s: {'✅ PASS' if throughput_pass else '❌ FAIL'} ({tx_per_sec:.1f} tx/s)")

    elif results.scenario == "config_poll":
        # Target: ~1 poll per device per minute.
        # Effective duration subtracts one poll_interval because:
        #   - startup jitter (0–poll_interval s) delays first poll per device
        #   - devices sleep poll_interval after their last poll before exiting
        # This means wall-clock duration is up to 2×poll_interval longer than
        # the requested test window; subtracting one interval gives the active
        # polling period (matching the heartbeat / msgspec effective-duration logic).
        poll_interval = 60  # seconds — matches DeviceConfig default
        throughput_target = results.num_devices / poll_interval
        effective_duration = max(results.duration_seconds - poll_interval, 1)
        effective_rps = results.total_requests / effective_duration
        throughput_pass = effective_rps >= throughput_target * 0.9
        print(f"Config Poll Rate >= {throughput_target:.1f} req/s: {'✅ PASS' if throughput_pass else '❌ FAIL'} ({effective_rps:.1f} req/s effective)")

    elif results.scenario == "cloud_commands":
        # Target: command delivery within heartbeat cycle
        throughput_target = results.num_devices / 30  # heartbeat every 30s
        throughput_pass = results.requests_per_second >= throughput_target * 0.9
        print(f"Command Throughput >= {throughput_target:.1f} req/s: {'✅ PASS' if throughput_pass else '❌ FAIL'} ({results.requests_per_second:.1f} req/s)")

    elif results.scenario == "wasm_steps":
        # Target: >90% step success rate; p95 execution < 300ms (simulated wasmtime budget)
        total_wasm = results.wasm_steps_executed + results.wasm_step_failures
        wasm_success_rate = results.wasm_steps_executed / total_wasm * 100 if total_wasm else 0
        wasm_pass = wasm_success_rate >= 90.0
        print(f"WASM success >= 90%:  {'✅ PASS' if wasm_pass else '❌ FAIL'} ({wasm_success_rate:.1f}%)")

        if results.wasm_execution_latencies:
            wl = sorted(results.wasm_execution_latencies)
            p95_wasm = wl[int(0.95 * (len(wl) - 1))] * 1000
            wasm_lat_pass = p95_wasm < 300.0
            print(f"WASM p95 < 300ms:     {'✅ PASS' if wasm_lat_pass else '❌ FAIL'} ({p95_wasm:.0f}ms)")

        # Throughput: steps-per-second across all devices
        wasm_tps = results.wasm_steps_executed / results.duration_seconds if results.duration_seconds > 0 else 0
        wasm_steps_per_sync = 5  # default from DeviceConfig
        target_tps = results.num_devices * wasm_steps_per_sync / results.duration_seconds if results.duration_seconds > 0 else 0
        tps_pass = wasm_tps >= target_tps * 0.9
        print(f"WASM steps/sec:       {wasm_tps:.1f}  (target: {target_tps:.1f}  {'✅ PASS' if tps_pass else '❌ FAIL'})")

    elif results.scenario == "wasm_thundering_herd":
        # WASM dispatch is local — no HTTP, no DB. Contrast vs SAF thundering herd.
        #
        # The only hard pass/fail is success rate: did every step complete without error?
        # Throughput and p99 are reported as informational — they scale non-linearly with
        # device count because all coroutines share a single asyncio event loop thread.
        # p99 measures asyncio scheduling backlog (time-in-queue), not WASM exec time.
        total_wasm = results.wasm_steps_executed + results.wasm_step_failures
        wasm_success_rate = results.wasm_steps_executed / total_wasm * 100 if total_wasm else 0
        wasm_pass = wasm_success_rate >= 99.0
        throughput = results.wasm_steps_executed / results.duration_seconds if results.duration_seconds > 0 else 0
        # steps_per_device_per_sec: normalises throughput by device count for apples-to-apples
        # comparison across runs at different scale. Stable target: >= 0.8 steps/device/sec
        # (each device completes its burst in ≤ wasm_steps_per_sync / 0.8 ≈ 6s).
        steps_per_device_per_sec = throughput / results.num_devices if results.num_devices else 0
        rate_pass = steps_per_device_per_sec >= 0.8
        print(f"Devices:              {results.num_devices:,}")
        print(f"WASM steps fired:     {total_wasm:,}")
        print(f"Device success >= 99%:{'✅ PASS' if wasm_pass else '❌ FAIL'} ({wasm_success_rate:.1f}%)")
        print(
            f"Rate >= 0.8/dev/s:    {'✅ PASS' if rate_pass else '❌ FAIL'} "
            f"({steps_per_device_per_sec:.2f} steps/device/sec  |  {throughput:,.0f} total steps/sec)"
        )
        if results.wasm_execution_latencies:
            wl = sorted(results.wasm_execution_latencies)
            p50_wasm = wl[int(0.50 * (len(wl) - 1))] * 1000
            p99_wasm = wl[int(0.99 * (len(wl) - 1))] * 1000
            baseline_p99_ms = 5055.0
            improvement = baseline_p99_ms / p99_wasm if p99_wasm > 0 else float('inf')
            print(f"Sched p50:            {p50_wasm:.2f}ms  ← asyncio queue depth, not exec time")
            print(f"Sched p99:            {p99_wasm:.2f}ms  (scales with device count)")
            print(f"Improvement vs SAF:   {improvement:.0f}x vs pre-Sovereign-Dispatcher SAF p99={baseline_p99_ms:.0f}ms")

    elif results.scenario == "thundering_herd":
        # Count devices that succeeded (sync_failures == 0 AND synced at least 1 tx)
        devices_succeeded = sum(
            1 for m in results.device_metrics.values()
            if m.sync_failures == 0 and m.transactions_synced > 0
        )
        total_devices = results.num_devices
        success_rate = devices_succeeded / total_devices * 100 if total_devices else 0
        herd_pass = success_rate >= 99.0
        print(f"Devices succeeded:    {devices_succeeded:,} / {total_devices:,}")
        print(f"Txns synced:          {results.transactions_synced:,}  ({results.transactions_synced // total_devices if total_devices else 0} avg/device)")
        print(f"Device success >= 99%:{'✅ PASS' if herd_pass else '❌ FAIL'} ({success_rate:.1f}%)")
        print(f"5xx errors:           {results.errors_5xx:,}  (pool/server limit)")
        print(f"Timeouts:             {results.errors_timeout:,}")
        if results.request_latencies:
            p_max = max(results.request_latencies) * 1000
            # Scale target with N: expected server capacity is ~500 req/s,
            # so the last device in a simultaneous burst of N waits N/500 seconds.
            per_worker_rps = 125  # req/s per worker (measured: 4 workers → ~500 req/s)
            expected_throughput = workers * per_worker_rps
            max_latency_target_ms = results.num_devices / expected_throughput * 1000
            tail_pass = p_max < max_latency_target_ms
            print(f"Max latency < {max_latency_target_ms / 1000:.0f}s:     {'✅ PASS' if tail_pass else '❌ FAIL'} ({p_max:.0f}ms)")

    elif results.scenario == "msgspec_codec":
        rps = results.total_requests / results.duration_seconds if results.duration_seconds > 0 else 0
        # Target: devices / heartbeat_interval (each device sends one heartbeat every 30s).
        # Effective duration accounts for the stagger ramp (up to heartbeat_interval seconds
        # before the first device fires), matching the heartbeat scenario accounting.
        heartbeat_interval = 30
        rps_target = results.num_devices / heartbeat_interval
        effective_duration = max(results.duration_seconds - heartbeat_interval, 1)
        effective_rps = results.total_requests / effective_duration
        rps_pass = effective_rps >= rps_target * 0.9
        print(f"Devices:              {results.num_devices:,}")
        print(f"Requests:             {results.total_requests:,}")
        print(f"Heartbeats sent:      {results.heartbeats_sent:,}")
        print(f"Req/sec >= {rps_target:.1f}:   {'✅ PASS' if rps_pass else '❌ FAIL'} ({effective_rps:.1f} req/sec effective)")
        print(f"Error rate:           {results.error_rate:.2f}%")

    elif results.scenario == "nats_transport":
        # NATS JetStream publish latency — no HTTP, measures ack round-trip only.
        # Target: p99 < 10ms (vs 50-300ms HTTP heartbeat path).
        print(f"Devices:              {results.num_devices:,}")
        print(f"Publishes sent:       {results.heartbeats_sent:,}")
        print(f"Publish failures:     {results.heartbeat_failures:,}")
        error_pass = results.error_rate < 1.0
        print(f"Error rate < 1%:      {'✅ PASS' if error_pass else '❌ FAIL'} ({results.error_rate:.2f}%)")
        if results.request_latencies:
            p50 = results.latency_percentile(0.50)
            p95 = results.latency_percentile(0.95)
            p99 = results.latency_percentile(0.99)
            # p99 target scales with load: <10ms at <=100 devices (idle NATS),
            # <25ms at <=1k, <50ms at <=10k, <150ms beyond.
            # Above 10k the asyncio scheduler backlog (not NATS itself) dominates p99 —
            # same pattern as wasm_thundering_herd. p50 stays <2ms even at 100k devices.
            if results.num_devices <= 100:
                p99_threshold = 10.0
            elif results.num_devices <= 1_000:
                p99_threshold = 25.0
            elif results.num_devices <= 10_000:
                p99_threshold = 50.0
            else:
                p99_threshold = 150.0
            p99_pass = p99 < p99_threshold
            print(f"Publish p50:          {p50:.2f}ms")
            print(f"Publish p95:          {p95:.2f}ms")
            print(f"Publish p99 < {p99_threshold:.0f}ms:  {'✅ PASS' if p99_pass else '❌ FAIL'} ({p99:.2f}ms)")
            print(f"Samples:              {len(results.request_latencies):,}")
        else:
            print("  (no latency samples — is RUVON_NATS_URL set and NATS server running?)")

    elif results.scenario == "ruvon_gossip":
        # RUVON capability gossip — measures vector serialise/publish/select pipeline.
        # Targets:
        #   - broadcast (encode + optional NATS publish) p95 < 1ms (no NATS) / < 50ms (NATS)
        #   - error rate < 1%
        print(f"Devices:              {results.num_devices:,}")
        total_gossip = results.gossip_broadcasts + results.gossip_failures
        gossip_success_rate = results.gossip_broadcasts / total_gossip * 100 if total_gossip else 0
        print(f"Gossip broadcasts:    {results.gossip_broadcasts:,}")
        print(f"Gossip failures:      {results.gossip_failures:,}")
        print(f"Error rate:           {results.error_rate:.2f}%")
        error_pass = results.error_rate < 1.0
        print(f"Error rate < 1%:      {'✅ PASS' if error_pass else '❌ FAIL'} ({results.error_rate:.2f}%)")
        if results.gossip_broadcast_latencies:
            gl = sorted(results.gossip_broadcast_latencies)
            p50_g = gl[int(0.50 * (len(gl) - 1))] * 1000
            p95_g = gl[int(0.95 * (len(gl) - 1))] * 1000
            p99_g = gl[int(0.99 * (len(gl) - 1))] * 1000
            p95_target = 50.0  # ms (NATS round-trip included)
            p95_pass = p95_g < p95_target
            print(f"Broadcast p50:        {p50_g:.2f}ms")
            print(f"Broadcast p95:        {p95_g:.2f}ms")
            print(f"Broadcast p99:        {p99_g:.2f}ms")
            print(f"Broadcast p95 < {p95_target:.0f}ms: {'✅ PASS' if p95_pass else '❌ FAIL'} ({p95_g:.2f}ms)")
            print(f"Samples:              {len(gl):,}")
        else:
            print("  (no latency samples — did gossip run?)")

    elif results.scenario == "nkey_patch":
        # NKey patch verification — Ed25519 signature verify throughput.
        # Targets:
        #   - error rate (incorrect accept or reject) < 0.1%
        #   - verify p95 < 5ms
        print(f"Devices:              {results.num_devices:,}")
        total_nkey = results.nkey_verifications + results.nkey_failures
        print(f"Total verifications:  {total_nkey:,}")
        print(f"Correct outcomes:     {results.nkey_verifications:,}")
        print(f"Incorrect outcomes:   {results.nkey_failures:,}")
        nkey_error_rate = results.nkey_failures / total_nkey * 100 if total_nkey else 0
        nkey_pass = nkey_error_rate < 0.1
        print(f"Verify accuracy > 99.9%: {'✅ PASS' if nkey_pass else '❌ FAIL'} ({100 - nkey_error_rate:.3f}% accurate)")
        if results.nkey_verify_latencies:
            nl = sorted(results.nkey_verify_latencies)
            p50_n = nl[int(0.50 * (len(nl) - 1))] * 1000
            p95_n = nl[int(0.95 * (len(nl) - 1))] * 1000
            p99_n = nl[int(0.99 * (len(nl) - 1))] * 1000
            p95_target_n = 5.0
            lat_pass = p95_n < p95_target_n
            print(f"Verify p50:           {p50_n:.2f}ms")
            print(f"Verify p95:           {p95_n:.2f}ms")
            print(f"Verify p99:           {p99_n:.2f}ms")
            print(f"Verify p95 < {p95_target_n:.0f}ms:    {'✅ PASS' if lat_pass else '❌ FAIL'} ({p95_n:.2f}ms)")
            print(f"Samples:              {len(nl):,}")
        else:
            print("  (no latency samples — did nkey_patch run? requires cryptography + ruvon-edge)")

    elif results.scenario == "mixed":
        # Mixed workload: heartbeat + gossip + SAF simultaneously.
        # Targets: SAF p99 < 500ms, gossip error rate < 1%, heartbeat error rate = 0%.
        print(f"Devices:              {results.num_devices:,}")
        print(f"Heartbeats sent:      {results.heartbeats_sent:,}")
        print(f"Heartbeat failures:   {results.heartbeat_failures:,}")
        hb_err = results.heartbeat_failures / (results.heartbeats_sent + results.heartbeat_failures) * 100 \
            if (results.heartbeats_sent + results.heartbeat_failures) else 0
        print(f"HB error rate = 0%:   {'✅ PASS' if hb_err == 0 else '❌ FAIL'} ({hb_err:.2f}%)")
        print(f"Transactions synced:  {results.transactions_synced:,}")
        print(f"Sync failures:        {results.sync_failures:,}")
        total_gossip = results.gossip_broadcasts + results.gossip_failures
        gossip_err_rate = results.gossip_failures / total_gossip * 100 if total_gossip else 0
        print(f"Gossip broadcasts:    {results.gossip_broadcasts:,}")
        print(f"Gossip error rate < 1%: {'✅ PASS' if gossip_err_rate < 1.0 else '❌ FAIL'} ({gossip_err_rate:.2f}%)")
        if results.request_latencies:
            p99 = results.latency_percentile(0.99)
            p99_pass = p99 < 500.0
            print(f"SAF p99 < 500ms:      {'✅ PASS' if p99_pass else '❌ FAIL'} ({p99:.1f}ms)")

    elif results.scenario == "election_stability":
        # Leader election stability: local score + re-election loop.
        # Targets: p95 election latency < 1ms, flap_count = 0, elections/min < 5.
        print(f"Devices:              {results.num_devices:,}")
        print(f"Elections run:        {results.elections_run:,}")
        print(f"Flap count:           {results.flap_count}")
        flap_pass = results.flap_count == 0
        print(f"Flap count = 0:       {'✅ PASS' if flap_pass else '❌ FAIL'}")
        if results.duration_seconds > 0:
            elections_per_min = results.elections_run / results.duration_seconds * 60
            epm_pass = elections_per_min < 5.0
            print(f"Elections/min < 5:    {'✅ PASS' if epm_pass else '❌ FAIL'} ({elections_per_min:.1f}/min)")
        if results.election_latencies:
            el = sorted(results.election_latencies)
            p95_e = el[int(0.95 * (len(el) - 1))] * 1000
            p95_pass = p95_e < 1.0
            print(f"Election p95 < 1ms:   {'✅ PASS' if p95_pass else '❌ FAIL'} ({p95_e:.3f}ms)")
            print(f"Samples:              {len(el):,}")
        if results.leader_tenure_samples:
            ts = sorted(results.leader_tenure_samples)
            p50_t = ts[int(0.50 * (len(ts) - 1))]
            print(f"Tenure p50:           {p50_t:.1f}s")

    elif results.scenario == "payload_variance":
        # Gossip payload variance: encode+decode at 256B/1KB/4KB/16KB/64KB.
        # Target: p95 encode+decode < 50ms even at 64KB.
        print(f"Devices:              {results.num_devices:,}")
        if results.payload_latencies:
            all_pass = True
            for label in ["256B", "1KB", "4KB", "16KB", "64KB"]:
                lats = results.payload_latencies.get(label, [])
                if not lats:
                    print(f"  {label:<6}:  (no samples)")
                    continue
                sl = sorted(lats)
                p95_ms = sl[int(0.95 * (len(sl) - 1))] * 1000
                p99_ms = sl[int(0.99 * (len(sl) - 1))] * 1000
                ok = p95_ms < 50.0
                all_pass = all_pass and ok
                print(f"  {label:<6}: p95={p95_ms:.2f}ms  p99={p99_ms:.2f}ms  n={len(sl):,}  "
                      f"{'✅' if ok else '❌'}")
            print(f"All sizes p95 < 50ms: {'✅ PASS' if all_pass else '❌ FAIL'}")
        else:
            print("  (no payload_latencies — did payload_variance run?)")

    elif results.scenario == "e2e_decision":
        # E2E decision pipeline: telemetry → score → sign → gossip → acks.
        # Targets: p50 < 50ms, p99 < 200ms.
        print(f"Devices:              {results.num_devices:,}")
        print(f"Ack count:            {results.e2e_ack_count:,}")
        if results.e2e_decision_latencies:
            el = sorted(results.e2e_decision_latencies)
            p50_ms = el[int(0.50 * (len(el) - 1))] * 1000
            p99_ms = el[int(0.99 * (len(el) - 1))] * 1000
            p50_pass = p50_ms < 50.0
            p99_pass = p99_ms < 200.0
            print(f"Decision p50 < 50ms:  {'✅ PASS' if p50_pass else '❌ FAIL'} ({p50_ms:.1f}ms)")
            print(f"Decision p99 < 200ms: {'✅ PASS' if p99_pass else '❌ FAIL'} ({p99_ms:.1f}ms)")
            print(f"Samples:              {len(el):,}")
        if results.e2e_consensus_latencies:
            cl = sorted(results.e2e_consensus_latencies)
            p50_c = cl[int(0.50 * (len(cl) - 1))] * 1000
            p99_c = cl[int(0.99 * (len(cl) - 1))] * 1000
            print(f"Consensus p50:        {p50_c:.1f}ms")
            print(f"Consensus p99:        {p99_c:.1f}ms")
        else:
            print("  (no e2e_decision_latencies — did e2e_decision run?)")

    print("=" * 80)


async def run_single_scenario(
    cloud_url: str,
    scenario: str,
    num_devices: int,
    duration: int,
    output_file: str
) -> LoadTestResults:
    """
    Run a single test scenario.

    This creates devices, registers them, runs the scenario, and cleans up.
    For running multiple scenarios, use run_all_scenarios() instead to share devices.
    """
    logger.info(f"Initializing load test orchestrator for {cloud_url}")

    orchestrator = LoadTestOrchestrator(
        cloud_url=cloud_url,
        base_api_key="load_test_api_key"
    )

    try:
        # Local-only scenarios (no HTTP calls) don't need server registration or cleanup
        _local_only = scenario in (
            "wasm_thundering_herd", "nats_transport", "ruvon_gossip", "nkey_patch",
            "election_stability", "payload_variance", "e2e_decision",
        )
        await orchestrator.setup_devices(
            num_devices,
            cleanup_first=not _local_only,
            register_with_server=not _local_only,
        )

        # Run scenario with existing devices
        results = await orchestrator.run_scenario(
            scenario=scenario,
            duration_seconds=duration,
            skip_device_setup=True  # Already set up
        )

        # Export results
        if output_file:
            orchestrator.export_results(results, output_file)

        return results

    finally:
        # Cleanup devices
        await orchestrator.teardown_devices()


async def run_all_scenarios(
    cloud_url: str,
    num_devices: int,
    output_dir: str,
    workers: int = 4,
    max_duration_per_scenario: int = None,
):
    """
    Run all test scenarios with shared devices.

    Devices are registered once at the start, used across all scenarios,
    and cleaned up once at the end. This avoids 401 errors and is more efficient.

    Args:
        max_duration_per_scenario: If set, caps each scenario duration to this many
            seconds (e.g. pass --duration 60 for a quick smoke run).
    """
    _DEFAULT_DURATIONS = [
        ("heartbeat", 600),
        ("saf_sync", 300),
        ("config_poll", 600),
        ("cloud_commands", 600),
        ("wasm_steps", 300),
        ("wasm_thundering_herd", 60),
        ("msgspec_codec", 120),
        ("nats_transport", 120),
        ("ruvon_gossip", 120),
        ("nkey_patch", 120),
        ("mixed", 300),
        ("election_stability", 120),
        ("payload_variance", 120),
        ("e2e_decision", 120),
    ]
    if max_duration_per_scenario:
        scenarios = [(s, min(d, max_duration_per_scenario)) for s, d in _DEFAULT_DURATIONS]
    else:
        scenarios = _DEFAULT_DURATIONS

    total_sec = sum(d for _, d in scenarios) + 5 * (len(scenarios) - 1)
    print(f"\nTotal estimated run time: {total_sec // 60}m {total_sec % 60}s "
          f"({len(scenarios)} scenarios, {num_devices} devices)\n")

    # Create single orchestrator for all scenarios
    logger.info("="*80)
    logger.info("LOAD TEST - ALL SCENARIOS")
    logger.info(f"Devices: {num_devices}")
    logger.info(f"Scenarios: {len(scenarios)}")
    logger.info("="*80)

    orchestrator = LoadTestOrchestrator(
        cloud_url=cloud_url,
        base_api_key="load_test_api_key"
    )

    try:
        # Setup devices once (register with control plane)
        print(f"Setting up {num_devices} devices (register once for all scenarios)...", flush=True)
        await orchestrator.setup_devices(num_devices, cleanup_first=True)
        print(f"Device setup complete.\n", flush=True)

        all_results = []

        # Run each scenario with the same devices
        for scenario, duration in scenarios:
            logger.info(f"\n{'='*80}")
            logger.info(f"Running scenario: {scenario.upper()}")
            logger.info(f"{'='*80}\n")

            output_file = f"{output_dir}/{scenario}_results.json" if output_dir else None

            idx = next(i for i, (s, _) in enumerate(scenarios) if s == scenario)
            print(f"[{idx + 1}/{len(scenarios)}] {scenario.upper()} — {duration}s", flush=True)

            def _progress(progress: dict, _s=scenario, _d=duration):
                elapsed = int(progress.get("elapsed_seconds", 0))
                pct = min(elapsed / _d * 100, 100) if _d else 0
                print(
                    f"  {_s}: {pct:5.1f}%  "
                    f"req={progress['total_requests']:,}  "
                    f"err={progress['total_errors']:,}  "
                    f"{progress['requests_per_second']:.1f} req/s",
                    flush=True,
                )

            # Run scenario (skip device setup since we already did it)
            results = await orchestrator.run_scenario(
                scenario=scenario,
                duration_seconds=duration,
                progress_callback=_progress,
                skip_device_setup=True  # Use existing devices
            )

            # Export results
            if output_file:
                orchestrator.export_results(results, output_file)

            print_results(results, workers=workers)
            all_results.append(results)

            # Brief pause between scenarios
            logger.info("Pausing 5 seconds before next scenario...\n")
            await asyncio.sleep(5)

        # Print summary
        print("\n" + "=" * 80)
        print("ALL SCENARIOS SUMMARY")
        print("=" * 80)
        print(f"{'Scenario':<22} {'Devices':>7} {'Requests':>9} {'Err%':>6} {'req/s':>7} {'p50ms':>7} {'p95ms':>7} {'p99ms':>7}  Status")
        print("-" * 80)

        for results in all_results:
            pass_fail = "✅" if results.error_rate < 1.0 else "❌"
            p50 = f"{results.latency_percentile(0.50):.0f}" if results.request_latencies else "  —"
            p95 = f"{results.latency_percentile(0.95):.0f}" if results.request_latencies else "  —"
            p99 = f"{results.latency_percentile(0.99):.0f}" if results.request_latencies else "  —"
            print(
                f"{results.scenario:<22} "
                f"{results.num_devices:>7} "
                f"{results.total_requests:>9,} "
                f"{results.error_rate:>6.2f} "
                f"{results.requests_per_second:>7.1f} "
                f"{p50:>7} "
                f"{p95:>7} "
                f"{p99:>7}  {pass_fail}"
            )

        print("=" * 80)

    finally:
        # Cleanup devices once at the end
        print("\nTearing down devices...", flush=True)
        await orchestrator.teardown_devices()
        print("Done.", flush=True)
        logger.info("Load test complete!")


def main():
    parser = argparse.ArgumentParser(
        description="Ruvon Edge Load Testing Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run heartbeat test with 1000 devices for 10 minutes
  python run_load_test.py --scenario heartbeat --devices 1000 --duration 600

  # Run SAF sync test with 500 devices
  python run_load_test.py --scenario saf_sync --devices 500

  # Run all scenarios with 100 devices (smoke test)
  python run_load_test.py --all --devices 100



  # Run with custom cloud URL and database URL
  python run_load_test.py --scenario heartbeat --devices 100 \\
      --cloud-url http://localhost:8000 \\
      --db-url "postgresql://rufus:password@localhost:5433/rufus_cloud"

  # Seed data check (automatic if DATABASE_URL env var set)
  export DATABASE_URL="postgresql://rufus:password@localhost:5433/rufus_cloud"
  python run_load_test.py --scenario heartbeat --devices 100

Scenarios:
  heartbeat          - Concurrent device heartbeats (30s interval)
  saf_sync           - Store-and-Forward bulk sync
  config_poll        - Config polling with ETag (60s interval)
  cloud_commands     - Cloud-to-device command delivery
  thundering_herd    - Synchronized SAF sync burst (all devices simultaneous)
  wasm_steps         - WASM step execution throughput (sync_wasm command delivery + edge execution)
  wasm_thundering_herd - Coordinated burst of local WASM dispatches (target: >= 0.8 steps/device/sec)
  msgspec_codec      - Heartbeat load with msgspec preflight (validates typed decode fast path)
  nats_transport     - Publish heartbeats directly to NATS JetStream (p99 <10ms @<=100, <25ms @<=1k, <50ms @<=10k, <150ms beyond)
  ruvon_gossip       - RUVON capability vector gossip (p95 <50ms broadcast, <1% error) [local-only, no server needed]
  nkey_patch         - NKey Ed25519 patch verification throughput (p95 <5ms, >99.9% accurate) [local-only]
        """
    )

    parser.add_argument(
        "--cloud-url",
        default=os.getenv("CLOUD_URL", "http://localhost:8000"),
        help="Cloud control plane URL (default: CLOUD_URL env var or http://localhost:8000)"
    )

    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL"),
        help="Database URL for seed data check (default: DATABASE_URL env var)"
    )

    parser.add_argument(
        "--scenario",
        choices=[
            "heartbeat",
            "saf_sync",
            "config_poll",
            "cloud_commands",
            "thundering_herd",
            "wasm_steps",
            "wasm_thundering_herd",
            "msgspec_codec",
            "nats_transport",
            "ruvon_gossip",
            "nkey_patch",
            "mixed",
            "election_stability",
            "payload_variance",
            "e2e_decision",
        ],
        help="Test scenario to run"
    )

    parser.add_argument(
        "--devices",
        type=int,
        default=100,
        help="Number of simulated devices (default: 100)"
    )

    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help=(
            "Test duration in seconds. With --scenario: sets the run length (default 600). "
            "With --all: caps each scenario to this duration (default: use scenario defaults)."
        )
    )

    parser.add_argument(
        "--output",
        help="Output file for results (JSON)"
    )

    parser.add_argument(
        "--output-dir",
        help="Output directory for all scenario results (with --all)"
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all scenarios"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of server workers (used to scale thundering herd latency target, default: 1)"
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)"
    )

    args = parser.parse_args()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Validate arguments
    if not args.all and not args.scenario:
        parser.error("Either --scenario or --all must be specified")

    # Ensure seed data exists before running tests
    if args.db_url:
        try:
            asyncio.run(ensure_seed_data(args.db_url))
        except Exception as e:
            logger.error(f"Failed to ensure seed data: {e}")
            logger.warning("Continuing with load test, but results may be affected")

    # Run tests
    try:
        if args.all:
            # Create output directory if needed
            if args.output_dir:
                Path(args.output_dir).mkdir(parents=True, exist_ok=True)

            asyncio.run(run_all_scenarios(
                cloud_url=args.cloud_url,
                num_devices=args.devices,
                output_dir=args.output_dir,
                workers=args.workers,
                max_duration_per_scenario=args.duration,
            ))
        else:
            results = asyncio.run(run_single_scenario(
                cloud_url=args.cloud_url,
                scenario=args.scenario,
                num_devices=args.devices,
                duration=args.duration or 600,
                output_file=args.output
            ))

            print_results(results, workers=args.workers)

    except KeyboardInterrupt:
        logger.info("\nLoad test interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Load test failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
