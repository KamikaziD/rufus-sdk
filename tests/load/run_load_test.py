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


def print_results(results: LoadTestResults):
    """Print formatted test results."""
    print("\n" + "=" * 80)
    print(f"LOAD TEST RESULTS - {results.scenario.upper()}")
    print("=" * 80)
    print(f"Devices:              {results.num_devices}")
    print(f"Duration:             {results.duration_seconds:.1f}s")
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

    print("=" * 80)

    # Check against targets
    print("\nPERFORMANCE TARGETS:")
    print("=" * 80)

    # Error rate target: < 1%
    error_pass = results.error_rate < 1.0
    print(f"Error Rate < 1%:      {'✅ PASS' if error_pass else '❌ FAIL'} ({results.error_rate:.2f}%)")

    # Throughput target (scenario-specific)
    if results.scenario == "heartbeat":
        # Target: 33 req/sec for 1000 devices (heartbeat every 30s)
        throughput_target = 33
        throughput_pass = results.requests_per_second >= throughput_target * 0.9  # 90% of target
        print(f"Throughput >= {throughput_target} req/s:  {'✅ PASS' if throughput_pass else '❌ FAIL'} ({results.requests_per_second:.1f} req/s)")

    elif results.scenario == "saf_sync":
        # Target: 1000 tx/sec
        tx_per_sec = results.transactions_synced / results.duration_seconds if results.duration_seconds > 0 else 0
        throughput_target = 1000
        throughput_pass = tx_per_sec >= throughput_target * 0.9
        print(f"Transaction Rate >= {throughput_target} tx/s: {'✅ PASS' if throughput_pass else '❌ FAIL'} ({tx_per_sec:.1f} tx/s)")

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
        # Setup devices for this scenario
        await orchestrator.setup_devices(num_devices, cleanup_first=True)

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
    output_dir: str
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
        ("model_update", 300),
        ("cloud_commands", 600),
        ("workflow_execution", 300),
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

            print_results(results)
            all_results.append(results)

            # Brief pause between scenarios
            logger.info("Pausing 5 seconds before next scenario...\n")
            await asyncio.sleep(5)

        # Print summary
        print("\n" + "=" * 80)
        print("ALL SCENARIOS SUMMARY")
        print("=" * 80)

        for results in all_results:
            pass_fail = "✅ PASS" if results.error_rate < 1.0 else "❌ FAIL"
            print(
                f"{results.scenario:20s} | "
                f"{results.num_devices:4d} devices | "
                f"{results.total_requests:7,} req | "
                f"{results.error_rate:5.2f}% err | "
                f"{pass_fail}"
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

  # Run with custom cloud URL
  python run_load_test.py --scenario heartbeat --devices 100 \\
      --cloud-url http://localhost:8000

Scenarios:
  heartbeat          - Concurrent device heartbeats (30s interval)
  saf_sync           - Store-and-Forward bulk sync
  config_poll        - Config polling with ETag (60s interval)
  model_update       - Model distribution with delta updates
  cloud_commands     - Cloud-to-device command delivery
  workflow_execution - Concurrent workflow execution
        """
    )

    parser.add_argument(
        "--cloud-url",
        default=os.getenv("CLOUD_URL", "http://localhost:8000"),
        help="Cloud control plane URL (default: CLOUD_URL env var or http://localhost:8000)"
    )

    parser.add_argument(
        "--scenario",
        choices=[
            "heartbeat",
            "saf_sync",
            "config_poll",
            "model_update",
            "cloud_commands",
            "workflow_execution"
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

    # Run tests
    try:
        if args.all:
            # Create output directory if needed
            if args.output_dir:
                Path(args.output_dir).mkdir(parents=True, exist_ok=True)

            asyncio.run(run_all_scenarios(
                cloud_url=args.cloud_url,
                num_devices=args.devices,
                output_dir=args.output_dir
            ))
        else:
            results = asyncio.run(run_single_scenario(
                cloud_url=args.cloud_url,
                scenario=args.scenario,
                num_devices=args.devices,
                duration=args.duration,
                output_file=args.output
            ))

            print_results(results)

    except KeyboardInterrupt:
        logger.info("\nLoad test interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Load test failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
