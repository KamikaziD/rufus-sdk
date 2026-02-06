"""
Load testing suite for Rufus Edge Cloud Control Plane.

Tests command versioning, webhook notifications, and overall system performance
under load.
"""

import asyncio
import httpx
import time
import statistics
import json
from typing import List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LoadTestResult:
    """Result from a load test."""
    test_name: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    duration_seconds: float
    requests_per_second: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    errors: List[str] = field(default_factory=list)


class LoadTester:
    """Base class for load testing."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: List[LoadTestResult] = []

    async def run_load_test(
        self,
        test_name: str,
        request_func,
        total_requests: int,
        concurrent_requests: int
    ) -> LoadTestResult:
        """
        Run a load test.

        Args:
            test_name: Name of the test
            request_func: Async function that makes a request
            total_requests: Total number of requests to make
            concurrent_requests: Number of concurrent requests

        Returns:
            LoadTestResult with statistics
        """
        print(f"\n{'='*70}")
        print(f"  Load Test: {test_name}")
        print(f"{'='*70}")
        print(f"  Total requests: {total_requests}")
        print(f"  Concurrent:     {concurrent_requests}")
        print()

        latencies = []
        successes = 0
        failures = 0
        errors = []

        start_time = time.time()

        # Create batches of concurrent requests
        batches = []
        for i in range(0, total_requests, concurrent_requests):
            batch_size = min(concurrent_requests, total_requests - i)
            batches.append(batch_size)

        # Run batches
        for batch_num, batch_size in enumerate(batches):
            tasks = []
            for _ in range(batch_size):
                tasks.append(self._timed_request(request_func))

            # Execute batch
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for result in results:
                if isinstance(result, Exception):
                    failures += 1
                    errors.append(str(result))
                elif isinstance(result, tuple):
                    success, latency, error = result
                    if success:
                        successes += 1
                        latencies.append(latency)
                    else:
                        failures += 1
                        if error:
                            errors.append(error)

            # Progress
            completed = sum(batches[:batch_num+1])
            print(f"  Progress: {completed}/{total_requests} requests "
                  f"({successes} success, {failures} failed)")

        duration = time.time() - start_time

        # Calculate statistics
        if latencies:
            avg_latency = statistics.mean(latencies)
            p50_latency = statistics.median(latencies)
            sorted_latencies = sorted(latencies)
            p95_latency = sorted_latencies[int(len(sorted_latencies) * 0.95)]
            p99_latency = sorted_latencies[int(len(sorted_latencies) * 0.99)]
            min_latency = min(latencies)
            max_latency = max(latencies)
        else:
            avg_latency = p50_latency = p95_latency = p99_latency = 0
            min_latency = max_latency = 0

        rps = total_requests / duration if duration > 0 else 0

        result = LoadTestResult(
            test_name=test_name,
            total_requests=total_requests,
            successful_requests=successes,
            failed_requests=failures,
            duration_seconds=duration,
            requests_per_second=rps,
            avg_latency_ms=avg_latency * 1000,
            p50_latency_ms=p50_latency * 1000,
            p95_latency_ms=p95_latency * 1000,
            p99_latency_ms=p99_latency * 1000,
            min_latency_ms=min_latency * 1000,
            max_latency_ms=max_latency * 1000,
            errors=errors[:10]  # Keep first 10 errors
        )

        self.results.append(result)
        self._print_result(result)

        return result

    async def _timed_request(self, request_func):
        """Execute a request and measure latency."""
        start = time.time()
        try:
            success = await request_func()
            latency = time.time() - start
            return (success, latency, None)
        except Exception as e:
            latency = time.time() - start
            return (False, latency, str(e))

    def _print_result(self, result: LoadTestResult):
        """Print test result."""
        print(f"\n  Results:")
        print(f"    Duration:       {result.duration_seconds:.2f}s")
        print(f"    Success:        {result.successful_requests}/{result.total_requests} "
              f"({result.successful_requests/result.total_requests*100:.1f}%)")
        print(f"    Failed:         {result.failed_requests}")
        print(f"    Throughput:     {result.requests_per_second:.2f} req/s")
        print(f"\n  Latency:")
        print(f"    Average:        {result.avg_latency_ms:.2f}ms")
        print(f"    p50:            {result.p50_latency_ms:.2f}ms")
        print(f"    p95:            {result.p95_latency_ms:.2f}ms")
        print(f"    p99:            {result.p99_latency_ms:.2f}ms")
        print(f"    Min:            {result.min_latency_ms:.2f}ms")
        print(f"    Max:            {result.max_latency_ms:.2f}ms")

        if result.errors:
            print(f"\n  Sample Errors:")
            for error in result.errors[:3]:
                print(f"    - {error}")

        print()

    def print_summary(self):
        """Print summary of all tests."""
        print(f"\n{'='*70}")
        print(f"  Load Test Summary")
        print(f"{'='*70}\n")

        for result in self.results:
            success_rate = result.successful_requests / result.total_requests * 100
            print(f"  {result.test_name}")
            print(f"    Requests:    {result.total_requests}")
            print(f"    Success:     {success_rate:.1f}%")
            print(f"    Throughput:  {result.requests_per_second:.2f} req/s")
            print(f"    p50 Latency: {result.p50_latency_ms:.2f}ms")
            print(f"    p95 Latency: {result.p95_latency_ms:.2f}ms")
            print()


class CommandVersioningLoadTest(LoadTester):
    """Load tests for command versioning."""

    async def test_validation_throughput(
        self,
        total_requests: int = 1000,
        concurrent: int = 50
    ):
        """Test validation endpoint throughput."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:

            async def validate_command():
                try:
                    response = await client.post(
                        "/api/v1/commands/restart/validate",
                        json={
                            "version": "1.0.0",
                            "data": {"delay_seconds": 10}
                        }
                    )
                    return response.status_code == 200
                except:
                    return False

            await self.run_load_test(
                "Command Validation Throughput",
                validate_command,
                total_requests,
                concurrent
            )

    async def test_list_versions_throughput(
        self,
        total_requests: int = 500,
        concurrent: int = 25
    ):
        """Test listing versions throughput."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:

            async def list_versions():
                try:
                    response = await client.get("/api/v1/commands/versions")
                    return response.status_code == 200
                except:
                    return False

            await self.run_load_test(
                "List Versions Throughput",
                list_versions,
                total_requests,
                concurrent
            )

    async def test_get_latest_version_throughput(
        self,
        total_requests: int = 1000,
        concurrent: int = 50
    ):
        """Test getting latest version throughput."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:

            async def get_latest():
                try:
                    response = await client.get("/api/v1/commands/restart/versions/latest")
                    return response.status_code == 200
                except:
                    return False

            await self.run_load_test(
                "Get Latest Version Throughput",
                get_latest,
                total_requests,
                concurrent
            )

    async def test_validation_with_errors(
        self,
        total_requests: int = 500,
        concurrent: int = 25
    ):
        """Test validation with invalid data (error path)."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:

            async def validate_invalid():
                try:
                    response = await client.post(
                        "/api/v1/commands/restart/validate",
                        json={
                            "version": "1.0.0",
                            "data": {"delay_seconds": 500}  # Invalid
                        }
                    )
                    # Should return 200 with valid=false
                    return response.status_code == 200 and not response.json()["valid"]
                except:
                    return False

            await self.run_load_test(
                "Validation Error Handling",
                validate_invalid,
                total_requests,
                concurrent
            )


class WebhookLoadTest(LoadTester):
    """Load tests for webhooks."""

    async def test_list_webhooks_throughput(
        self,
        total_requests: int = 500,
        concurrent: int = 25
    ):
        """Test listing webhooks throughput."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:

            async def list_webhooks():
                try:
                    response = await client.get("/api/v1/webhooks")
                    return response.status_code == 200
                except:
                    return False

            await self.run_load_test(
                "List Webhooks Throughput",
                list_webhooks,
                total_requests,
                concurrent
            )

    async def test_webhook_creation_throughput(
        self,
        total_requests: int = 100,
        concurrent: int = 10
    ):
        """Test webhook creation throughput."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:

            request_count = 0

            async def create_webhook():
                nonlocal request_count
                request_count += 1

                webhook_id = f"load-test-webhook-{request_count}-{time.time()}"

                try:
                    response = await client.post(
                        "/api/v1/webhooks",
                        json={
                            "webhook_id": webhook_id,
                            "name": "Load Test Webhook",
                            "url": "http://example.com/webhook",
                            "events": ["device.online"]
                        }
                    )
                    return response.status_code == 200
                except:
                    return False

            await self.run_load_test(
                "Webhook Creation Throughput",
                create_webhook,
                total_requests,
                concurrent
            )

    async def test_get_webhook_throughput(
        self,
        total_requests: int = 500,
        concurrent: int = 25
    ):
        """Test getting webhook details throughput."""
        # Create a test webhook first
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            webhook_id = f"load-test-get-webhook-{time.time()}"

            await client.post(
                "/api/v1/webhooks",
                json={
                    "webhook_id": webhook_id,
                    "name": "Load Test Get Webhook",
                    "url": "http://example.com/webhook",
                    "events": ["device.online"]
                }
            )

            async def get_webhook():
                try:
                    response = await client.get(f"/api/v1/webhooks/{webhook_id}")
                    return response.status_code == 200
                except:
                    return False

            await self.run_load_test(
                "Get Webhook Throughput",
                get_webhook,
                total_requests,
                concurrent
            )


class MixedWorkloadLoadTest(LoadTester):
    """Mixed workload load tests."""

    async def test_mixed_workload(
        self,
        total_requests: int = 1000,
        concurrent: int = 50
    ):
        """Test mixed workload (validation + webhooks)."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:

            import random

            async def mixed_request():
                try:
                    # Randomly choose operation
                    op = random.choice(['validate', 'list_versions', 'list_webhooks'])

                    if op == 'validate':
                        response = await client.post(
                            "/api/v1/commands/restart/validate",
                            json={
                                "version": "1.0.0",
                                "data": {"delay_seconds": 10}
                            }
                        )
                    elif op == 'list_versions':
                        response = await client.get("/api/v1/commands/versions")
                    else:  # list_webhooks
                        response = await client.get("/api/v1/webhooks")

                    return response.status_code == 200
                except:
                    return False

            await self.run_load_test(
                "Mixed Workload",
                mixed_request,
                total_requests,
                concurrent
            )


async def main():
    """Run all load tests."""
    print("\n" + "="*70)
    print("  Rufus Edge Load Testing Suite")
    print("="*70)
    print(f"\n  Target: http://localhost:8000")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Command versioning tests
    print("\n" + "="*70)
    print("  Command Versioning Load Tests")
    print("="*70)

    cmd_test = CommandVersioningLoadTest()
    await cmd_test.test_validation_throughput(total_requests=1000, concurrent=50)
    await cmd_test.test_list_versions_throughput(total_requests=500, concurrent=25)
    await cmd_test.test_get_latest_version_throughput(total_requests=1000, concurrent=50)
    await cmd_test.test_validation_with_errors(total_requests=500, concurrent=25)

    # Webhook tests
    print("\n" + "="*70)
    print("  Webhook Load Tests")
    print("="*70)

    webhook_test = WebhookLoadTest()
    await webhook_test.test_list_webhooks_throughput(total_requests=500, concurrent=25)
    await webhook_test.test_webhook_creation_throughput(total_requests=100, concurrent=10)
    await webhook_test.test_get_webhook_throughput(total_requests=500, concurrent=25)

    # Mixed workload
    print("\n" + "="*70)
    print("  Mixed Workload Tests")
    print("="*70)

    mixed_test = MixedWorkloadLoadTest()
    await mixed_test.test_mixed_workload(total_requests=1000, concurrent=50)

    # Print summaries
    cmd_test.print_summary()
    webhook_test.print_summary()
    mixed_test.print_summary()

    print("="*70)
    print(f"  Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
