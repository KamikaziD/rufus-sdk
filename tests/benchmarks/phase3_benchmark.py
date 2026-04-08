"""
Phase 3 Alembic Migration - Performance Benchmark

Compares raw SQL vs SQLAlchemy Core for read operations.
This benchmark tests the hybrid approach for the Go/No-Go decision.

Usage:
    python tests/benchmarks/phase3_benchmark.py
"""

import asyncio
import time
import statistics
import uuid
from typing import List, Dict

from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider


class BenchmarkResult:
    """Container for benchmark results"""

    def __init__(self, name: str):
        self.name = name
        self.times: List[float] = []

    def add_time(self, elapsed: float):
        self.times.append(elapsed)

    def get_stats(self) -> Dict[str, float]:
        if not self.times:
            return {}

        return {
            'mean_ms': statistics.mean(self.times) * 1000,
            'median_ms': statistics.median(self.times) * 1000,
            'p95_ms': self._percentile(self.times, 0.95) * 1000,
            'p99_ms': self._percentile(self.times, 0.99) * 1000,
            'ops_per_sec': len(self.times) / sum(self.times) if sum(self.times) > 0 else 0,
        }

    def _percentile(self, data: List[float], percentile: float) -> float:
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile)
        return sorted_data[min(index, len(sorted_data) - 1)]


async def main():
    print("="*70)
    print("  PHASE 3 PERFORMANCE BENCHMARK - Raw SQL Baseline")
    print("="*70)
    print()

    # Connect to PostgreSQL
    db_url = "postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_cloud"
    provider = PostgresPersistenceProvider(db_url)
    await provider.initialize()

    # Prepare test data
    print("Preparing test workflows...")
    workflow_ids = [str(uuid.uuid4()) for _ in range(100)]

    for i, wf_id in enumerate(workflow_ids):
        workflow_data = {
            'id': wf_id,
            'workflow_type': 'BenchmarkWorkflow',
            'workflow_version': 'v1',
            'current_step': 'Step1',
            'status': 'ACTIVE' if i % 2 == 0 else 'COMPLETED',
            'state': {'iteration': i, 'data': {'key': f'value_{i}'}},
            'definition_snapshot': None,
            'steps_config': [
                {'name': 'Step1', 'type': 'STANDARD'},
                {'name': 'Step2', 'type': 'ASYNC'},
            ],
            'state_model_path': 'benchmark.State',
            'saga_mode': False,
            'completed_steps_stack': [],
            'parent_execution_id': None,
            'blocked_on_child_id': None,
            'data_region': 'us-east-1',
            'priority': 5,
            'idempotency_key': None,
            'metadata': {},
            'owner_id': None,
            'org_id': None,
            'encrypted_state': None,
            'encryption_key_id': None,
            'error_message': None,
        }
        await provider.save_workflow(wf_id, workflow_data)

    print(f"✓ Created {len(workflow_ids)} test workflows\n")

    # Benchmark: save_workflow (write operation)
    print("Benchmarking save_workflow (WRITE - Raw SQL)...")
    save_result = BenchmarkResult("save_workflow")
    for i in range(50):
        wf_id = str(uuid.uuid4())
        workflow_data = {
            'id': wf_id,
            'workflow_type': 'BenchmarkWorkflow',
            'workflow_version': 'v1',
            'current_step': 'Step1',
            'status': 'ACTIVE',
            'state': {'iteration': i},
            'definition_snapshot': None,
            'steps_config': [],
            'state_model_path': 'benchmark.State',
            'saga_mode': False,
            'completed_steps_stack': [],
            'parent_execution_id': None,
            'blocked_on_child_id': None,
            'data_region': 'us-east-1',
            'priority': 5,
            'idempotency_key': None,
            'metadata': {},
            'owner_id': None,
            'org_id': None,
            'encrypted_state': None,
            'encryption_key_id': None,
            'error_message': None,
        }

        start = time.perf_counter()
        await provider.save_workflow(wf_id, workflow_data)
        elapsed = time.perf_counter() - start
        save_result.add_time(elapsed)

    # Benchmark: load_workflow (read operation)
    print("Benchmarking load_workflow (READ - Raw SQL)...")
    load_result = BenchmarkResult("load_workflow")
    for wf_id in workflow_ids[:50]:
        start = time.perf_counter()
        await provider.load_workflow(wf_id)
        elapsed = time.perf_counter() - start
        load_result.add_time(elapsed)

    # Benchmark: list_workflows (read operation)
    print("Benchmarking list_workflows (READ - Raw SQL)...")
    list_result = BenchmarkResult("list_workflows")
    for _ in range(30):
        start = time.perf_counter()
        await provider.list_workflows(status='ACTIVE', limit=50)
        elapsed = time.perf_counter() - start
        list_result.add_time(elapsed)

    # Print results
    print("\n" + "="*70)
    print("  BASELINE RESULTS (Raw SQL)")
    print("="*70 + "\n")

    for result in [save_result, load_result, list_result]:
        stats = result.get_stats()
        print(f"{result.name.upper()}")
        print("-"*70)
        print(f"  Mean:        {stats['mean_ms']:>10.3f} ms")
        print(f"  Median:      {stats['median_ms']:>10.3f} ms")
        print(f"  P95:         {stats['p95_ms']:>10.3f} ms")
        print(f"  P99:         {stats['p99_ms']:>10.3f} ms")
        print(f"  Throughput:  {stats['ops_per_sec']:>10.1f} ops/sec")
        print()

    # Cleanup
    print("Cleaning up test data...")
    async with provider.pool.acquire() as conn:
        await conn.execute("DELETE FROM workflow_executions WHERE workflow_type = 'BenchmarkWorkflow'")

    await provider.close()
    print("✓ Benchmark complete!\n")


if __name__ == '__main__':
    asyncio.run(main())
