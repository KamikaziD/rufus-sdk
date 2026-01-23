"""
Performance Benchmarks for Rufus SDK

This script benchmarks key performance metrics:
- Workflow throughput (workflows/sec)
- Step execution latency (p50, p95, p99)
- Serialization performance
- Import caching effectiveness
"""

import asyncio
import time
import statistics
from typing import List, Dict, Any
from pydantic import BaseModel

# Test if optimizations are enabled
from rufus.utils.serialization import get_backend
import rufus


class BenchmarkState(BaseModel):
    """Simple state model for benchmarking"""
    workflow_id: str
    data: Dict[str, Any] = {}
    counter: int = 0


def simple_step(state: BenchmarkState, context: Any) -> dict:
    """Simple step function for benchmarking"""
    state.counter += 1
    return {"processed": True, "counter": state.counter}


def benchmark_serialization(iterations: int = 10000):
    """Benchmark JSON serialization performance"""
    from rufus.utils.serialization import serialize, deserialize

    test_data = {
        "workflow_id": "test_123",
        "state": {
            "user_id": "user_456",
            "amount": 50000,
            "status": "processing",
            "metadata": {
                "created_at": "2024-01-01T00:00:00Z",
                "tags": ["important", "high-priority"],
            }
        },
        "steps_config": [
            {"name": "step1", "type": "STANDARD"},
            {"name": "step2", "type": "ASYNC"},
        ]
    }

    # Warmup
    for _ in range(100):
        s = serialize(test_data)
        deserialize(s)

    # Benchmark serialization
    start = time.perf_counter()
    for _ in range(iterations):
        serialized = serialize(test_data)
    serialize_time = time.perf_counter() - start

    # Benchmark deserialization
    serialized = serialize(test_data)
    start = time.perf_counter()
    for _ in range(iterations):
        deserialized = deserialize(serialized)
    deserialize_time = time.perf_counter() - start

    return {
        "iterations": iterations,
        "serialize_time_ms": serialize_time * 1000,
        "serialize_ops_per_sec": iterations / serialize_time,
        "deserialize_time_ms": deserialize_time * 1000,
        "deserialize_ops_per_sec": iterations / deserialize_time,
        "backend": get_backend(),
    }


def benchmark_import_caching(iterations: int = 1000):
    """Benchmark import caching effectiveness"""
    from rufus.builder import WorkflowBuilder

    # Clear cache for accurate measurement
    WorkflowBuilder._import_cache.clear()

    # Use a real rufus function for testing
    test_path = "rufus.utils.serialization.serialize"

    # First import (cache miss)
    start = time.perf_counter()
    func1 = WorkflowBuilder._import_from_string(test_path)
    first_import_time = time.perf_counter() - start

    # Subsequent imports (cache hits)
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        func = WorkflowBuilder._import_from_string(test_path)
        times.append(time.perf_counter() - start)

    return {
        "iterations": iterations,
        "first_import_ms": first_import_time * 1000,
        "cached_import_avg_ms": statistics.mean(times) * 1000,
        "speedup": first_import_time / statistics.mean(times),
        "cache_size": len(WorkflowBuilder._import_cache),
    }


async def benchmark_async_overhead(iterations: int = 1000):
    """Benchmark async/await overhead with uvloop vs stdlib"""

    async def simple_async_task():
        """Minimal async task"""
        await asyncio.sleep(0)
        return True

    # Warmup
    for _ in range(100):
        await simple_async_task()

    # Benchmark
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        await simple_async_task()
        times.append(time.perf_counter() - start)

    return {
        "iterations": iterations,
        "avg_latency_us": statistics.mean(times) * 1_000_000,
        "p50_latency_us": statistics.median(times) * 1_000_000,
        "p95_latency_us": statistics.quantiles(times, n=20)[18] * 1_000_000,
        "p99_latency_us": statistics.quantiles(times, n=100)[98] * 1_000_000,
        "event_loop_type": type(asyncio.get_event_loop()).__name__,
    }


async def benchmark_workflow_throughput(num_workflows: int = 1000):
    """
    Benchmark workflow execution throughput

    Note: This is a simplified benchmark using in-memory execution.
    For realistic benchmarks, use the full WorkflowBuilder with persistence.
    """
    from rufus.models import StepContext

    # Simulate workflow executions
    workflows = []
    for i in range(num_workflows):
        state = BenchmarkState(workflow_id=f"wf_{i}", data={"test": "data"})
        workflows.append(state)

    # Warmup
    for state in workflows[:100]:
        context = StepContext(workflow_id=state.workflow_id, step_name="test", previous_step_result={})
        simple_step(state, context)

    # Benchmark
    start = time.perf_counter()
    for state in workflows:
        context = StepContext(workflow_id=state.workflow_id, step_name="test", previous_step_result={})
        simple_step(state, context)
    elapsed = time.perf_counter() - start

    return {
        "num_workflows": num_workflows,
        "elapsed_seconds": elapsed,
        "throughput_per_sec": num_workflows / elapsed,
        "avg_latency_ms": (elapsed / num_workflows) * 1000,
    }


def print_benchmark_results(name: str, results: Dict[str, Any]):
    """Pretty print benchmark results"""
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    for key, value in results.items():
        if isinstance(value, float):
            print(f"  {key:30s}: {value:,.2f}")
        else:
            print(f"  {key:30s}: {value}")
    print(f"{'='*60}\n")


async def run_all_benchmarks():
    """Run all performance benchmarks"""
    print("\n" + "="*60)
    print("  RUFUS SDK PHASE 1 PERFORMANCE BENCHMARKS")
    print("="*60)
    print(f"\n  Optimizations Enabled:")
    print(f"    - Serialization Backend: {get_backend()}")
    print(f"    - Event Loop Backend: {rufus._event_loop_backend}")
    print(f"    - Import Caching: Enabled")
    print()

    # Run benchmarks
    print("\n[1/4] Benchmarking JSON Serialization...")
    serialization_results = benchmark_serialization(iterations=10000)
    print_benchmark_results("JSON Serialization Performance", serialization_results)

    print("[2/4] Benchmarking Import Caching...")
    import_results = benchmark_import_caching(iterations=1000)
    print_benchmark_results("Import Caching Performance", import_results)

    print("[3/4] Benchmarking Async Overhead...")
    async_results = await benchmark_async_overhead(iterations=1000)
    print_benchmark_results("Async/Await Overhead", async_results)

    print("[4/4] Benchmarking Workflow Throughput...")
    throughput_results = await benchmark_workflow_throughput(num_workflows=1000)
    print_benchmark_results("Workflow Execution Throughput", throughput_results)

    # Summary
    print("\n" + "="*60)
    print("  SUMMARY")
    print("="*60)
    print(f"  Serialization: {serialization_results['serialize_ops_per_sec']:,.0f} ops/sec ({serialization_results['backend']})")
    print(f"  Import Cache: {import_results['speedup']:.1f}x speedup")
    print(f"  Async Latency: {async_results['p50_latency_us']:.1f}µs (p50), {async_results['p99_latency_us']:.1f}µs (p99)")
    print(f"  Workflow Throughput: {throughput_results['throughput_per_sec']:,.0f} workflows/sec")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(run_all_benchmarks())
