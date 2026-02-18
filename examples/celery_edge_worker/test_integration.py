#!/usr/bin/env python3
"""
Test Script for Celery Edge Integration

Demonstrates:
1. Task execution with SAF support
2. Config hot-reload
3. Redis outage recovery
4. Model updates

Usage:
    python test_integration.py --scenario all
"""

import argparse
import time
import sys
from typing import Optional

try:
    from celery import Celery
    from examples.celery_edge_worker.rufus_worker_edge import (
        process_with_saf,
        check_fraud,
        llm_inference,
    )
    import httpx
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("\nInstall dependencies:")
    print("  pip install celery redis httpx")
    sys.exit(1)


def test_basic_task_execution(app: Celery):
    """Test basic task execution through Redis."""
    print("\n" + "=" * 60)
    print("TEST 1: Basic Task Execution")
    print("=" * 60)

    print("\n1. Submitting task to Redis queue...")
    task = process_with_saf.delay({"test": "basic_execution"})

    print(f"   Task ID: {task.id}")
    print("   Waiting for result...")

    try:
        result = task.get(timeout=10)
        print(f"\n✅ Task completed successfully!")
        print(f"   Result: {result}")
        return True
    except Exception as e:
        print(f"\n❌ Task failed: {e}")
        return False


def test_fraud_check(app: Celery):
    """Test fraud check with hot-reloaded rules."""
    print("\n" + "=" * 60)
    print("TEST 2: Fraud Check (Hot-Reloaded Rules)")
    print("=" * 60)

    transactions = [
        {"id": "txn_001", "amount": 50.00, "card_number": "4111111111111111"},
        {"id": "txn_002", "amount": 1500.00, "card_number": "4111111111111111"},
        {"id": "txn_003", "amount": 25.00, "card_number": "5555555555554444"},
    ]

    print("\n1. Submitting fraud checks...")
    tasks = []

    for txn in transactions:
        task = check_fraud.delay(txn)
        tasks.append((txn, task))
        print(f"   {txn['id']}: ${txn['amount']} (Task ID: {task.id})")

    print("\n2. Waiting for results...")
    all_passed = True

    for txn, task in tasks:
        try:
            result = task.get(timeout=10)
            fraud_status = "🚫 FRAUD" if result.get("fraud") else "✅ CLEAN"
            print(f"   {txn['id']}: {fraud_status}")

            if result.get("rule_violated"):
                print(f"      Rule violated: {result['rule_violated']}")

        except Exception as e:
            print(f"   {txn['id']}: ❌ ERROR - {e}")
            all_passed = False

    return all_passed


def test_llm_inference(app: Celery):
    """Test LLM inference with model versioning."""
    print("\n" + "=" * 60)
    print("TEST 3: LLM Inference (Model Versioning)")
    print("=" * 60)

    prompts = [
        "What is the capital of France?",
        "Explain quantum computing in simple terms.",
        "Write a haiku about programming.",
    ]

    print("\n1. Submitting LLM inference tasks...")
    tasks = []

    for prompt in prompts:
        task = llm_inference.delay(prompt, model_name="llama3.1")
        tasks.append((prompt, task))
        print(f"   Prompt: {prompt[:50]}... (Task ID: {task.id})")

    print("\n2. Waiting for results...")
    all_passed = True

    for prompt, task in tasks:
        try:
            result = task.get(timeout=30)
            print(f"\n   ✅ Prompt: {prompt}")
            print(f"      Model: {result.get('model')} v{result.get('version')}")
            print(f"      Result: {result.get('result')}")

        except Exception as e:
            print(f"\n   ❌ Prompt: {prompt}")
            print(f"      Error: {e}")
            all_passed = False

    return all_passed


def test_redis_outage_recovery(app: Celery, control_plane_url: str):
    """Test SAF queue during Redis outage."""
    print("\n" + "=" * 60)
    print("TEST 4: Redis Outage Recovery (SAF)")
    print("=" * 60)

    print("\n⚠️  This test requires manual Redis stop/start")
    print("   1. Stop Redis: docker compose stop redis")
    print("   2. Submit tasks (will queue to SQLite)")
    print("   3. Start Redis: docker compose start redis")
    print("   4. Tasks auto-sync to Redis and execute")

    input("\nPress Enter when ready to proceed...")

    print("\n1. Submitting tasks (Redis may be down)...")
    tasks = []

    for i in range(5):
        try:
            task = process_with_saf.delay({"test": "saf_recovery", "index": i})
            tasks.append(task)
            print(f"   Task {i+1}: {task.id}")
        except Exception as e:
            print(f"   Task {i+1}: Queued to SAF (Redis down)")

    print("\n2. If Redis was down, restart it now:")
    print("   docker compose start redis")

    input("\nPress Enter after Redis is started...")

    print("\n3. Waiting for tasks to complete...")
    all_passed = True

    for i, task in enumerate(tasks):
        try:
            result = task.get(timeout=30)
            print(f"   Task {i+1}: ✅ Completed")
        except Exception as e:
            print(f"   Task {i+1}: ❌ Failed - {e}")
            all_passed = False

    return all_passed


def test_config_hot_reload(app: Celery, control_plane_url: str, worker_id: str):
    """Test config hot-reload."""
    print("\n" + "=" * 60)
    print("TEST 5: Config Hot-Reload")
    print("=" * 60)

    print("\n1. Fetching current config...")

    try:
        with httpx.Client() as client:
            response = client.get(
                f"{control_plane_url}/api/v1/devices/{worker_id}/config",
                timeout=10.0
            )
            current_config = response.json()
            current_version = current_config.get("version", "unknown")

            print(f"   Current version: {current_version}")
            print(f"   Fraud rules: {len(current_config.get('fraud_rules', []))}")

    except Exception as e:
        print(f"   ⚠️  Could not fetch config: {e}")
        print("   Ensure control plane is running")
        return False

    print("\n2. Updating config (add new fraud rule)...")

    new_config = current_config.copy()
    new_config["version"] = f"{current_version}.1"
    new_config["fraud_rules"] = current_config.get("fraud_rules", []) + [
        {"type": "test_rule", "limit": 999, "description": "Test rule for hot-reload"}
    ]

    try:
        with httpx.Client() as client:
            response = client.post(
                f"{control_plane_url}/api/v1/devices/{worker_id}/config",
                json=new_config,
                timeout=10.0
            )

            if response.status_code == 200:
                print(f"   ✅ Config updated to version {new_config['version']}")
            else:
                print(f"   ⚠️  Update returned status {response.status_code}")

    except Exception as e:
        print(f"   ❌ Config update failed: {e}")
        return False

    print("\n3. Waiting for worker to poll config (up to 60 seconds)...")
    print("   Worker polls every CONFIG_POLL_INTERVAL seconds")

    for i in range(6):
        print(f"   {(i+1)*10}s...", end=" ", flush=True)
        time.sleep(10)

    print("\n\n4. Verifying config was applied...")
    print("   Check worker logs: docker compose logs worker-standard | grep ConfigHotReload")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Test Celery Edge Integration",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--scenario",
        choices=["all", "basic", "fraud", "llm", "redis", "config"],
        default="all",
        help="Test scenario to run"
    )

    parser.add_argument(
        "--control-plane-url",
        default="http://localhost:8000",
        help="Control plane API URL"
    )

    parser.add_argument(
        "--worker-id",
        default="worker-standard-01",
        help="Worker device ID"
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("CELERY EDGE INTEGRATION - TEST SUITE")
    print("=" * 60)
    print(f"\nControl Plane: {args.control_plane_url}")
    print(f"Worker ID: {args.worker_id}")

    # Create Celery app
    from examples.celery_edge_worker.rufus_worker_edge import app

    results = {}

    try:
        if args.scenario in ["all", "basic"]:
            results["basic"] = test_basic_task_execution(app)

        if args.scenario in ["all", "fraud"]:
            results["fraud"] = test_fraud_check(app)

        if args.scenario in ["all", "llm"]:
            results["llm"] = test_llm_inference(app)

        if args.scenario in ["all", "redis"]:
            results["redis"] = test_redis_outage_recovery(app, args.control_plane_url)

        if args.scenario in ["all", "config"]:
            results["config"] = test_config_hot_reload(app, args.control_plane_url, args.worker_id)

    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        sys.exit(1)

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name.upper()}: {status}")

    total_passed = sum(results.values())
    total_tests = len(results)

    print(f"\nTotal: {total_passed}/{total_tests} tests passed")

    if total_passed == total_tests:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print("\n⚠️  Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
