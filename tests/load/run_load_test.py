#!/usr/bin/env python3
"""
Rufus Load Test Runner.

Command-line interface for running load tests against Rufus Edge control plane.

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

from tests.load.orchestrator import LoadTestOrchestrator, ScenarioRunner, LoadTestResults

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('load_test.log')
    ]
)

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
        # Target: config polling should sustain reasonable rate
        throughput_target = results.num_devices / 60  # ~1 poll per device per minute
        throughput_pass = results.requests_per_second >= throughput_target * 0.9
        print(f"Config Poll Rate >= {throughput_target:.1f} req/s: {'✅ PASS' if throughput_pass else '❌ FAIL'} ({results.requests_per_second:.1f} req/s)")

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
        rps_pass = rps >= 50.0  # sanity floor — preflight + heartbeat should always clear this
        print(f"Devices:              {results.num_devices:,}")
        print(f"Requests:             {results.total_requests:,}")
        print(f"Heartbeats sent:      {results.heartbeats_sent:,}")
        print(f"Req/sec >= 50:        {'✅ PASS' if rps_pass else '❌ FAIL'} ({rps:.1f} req/sec)")
        print(f"Error rate:           {results.error_rate:.2f}%")

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
        _local_only = scenario in ("wasm_thundering_herd",)
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
):
    """
    Run all test scenarios with shared devices.

    Devices are registered once at the start, used across all scenarios,
    and cleaned up once at the end. This avoids 401 errors and is more efficient.
    """
    scenarios = [
        ("heartbeat", 600),
        ("saf_sync", 300),
        ("config_poll", 600),
        ("cloud_commands", 600),
        ("wasm_steps", 300),
        ("wasm_thundering_herd", 60),
        ("msgspec_codec", 120),
    ]

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
        logger.info("\n" + "="*80)
        logger.info("DEVICE SETUP - Registering devices for all scenarios")
        logger.info("="*80)
        await orchestrator.setup_devices(num_devices, cleanup_first=True)

        all_results = []

        # Run each scenario with the same devices
        for scenario, duration in scenarios:
            logger.info(f"\n{'='*80}")
            logger.info(f"Running scenario: {scenario.upper()}")
            logger.info(f"{'='*80}\n")

            output_file = f"{output_dir}/{scenario}_results.json" if output_dir else None

            # Run scenario (skip device setup since we already did it)
            results = await orchestrator.run_scenario(
                scenario=scenario,
                duration_seconds=duration,
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
        logger.info("\n" + "="*80)
        logger.info("DEVICE TEARDOWN - Cleaning up all devices")
        logger.info("="*80)
        await orchestrator.teardown_devices()
        logger.info("Load test complete!")


def main():
    parser = argparse.ArgumentParser(
        description="Rufus Edge Load Testing Tool",
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
        default=600,
        help="Test duration in seconds (default: 600)"
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
            ))
        else:
            results = asyncio.run(run_single_scenario(
                cloud_url=args.cloud_url,
                scenario=args.scenario,
                num_devices=args.devices,
                duration=args.duration,
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
