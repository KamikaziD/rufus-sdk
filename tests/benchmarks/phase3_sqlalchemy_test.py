"""
Phase 3 - SQLAlchemy Core Hybrid Approach Test

Tests SQLAlchemy Core query building with asyncpg execution.
Compares performance against raw SQL baseline.
"""

import asyncio
import time
import statistics
import uuid
from typing import List, Dict

import asyncpg
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from ruvon.db_schema import workflow_executions
from ruvon.implementations.persistence.postgres import PostgresPersistenceProvider


class HybridBenchmark:
    """Test SQLAlchemy Core queries with asyncpg execution"""

    def __init__(self, provider: PostgresPersistenceProvider):
        self.provider = provider
        self.results = {}

    async def list_workflows_raw_sql(self, **filters) -> List[Dict]:
        """Original raw SQL implementation"""
        async with self.provider.pool.acquire() as conn:
            query = "SELECT id, workflow_type, current_step, status, updated_at FROM workflow_executions"
            params = []
            conditions = []

            if 'status' in filters:
                conditions.append(f"status = ${len(params) + 1}")
                params.append(filters['status'])
            if 'workflow_type' in filters:
                conditions.append(f"workflow_type = ${len(params) + 1}")
                params.append(filters['workflow_type'])
            if 'limit' in filters:
                limit = filters['limit']
            else:
                limit = 100

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += f" ORDER BY updated_at DESC LIMIT {limit}"

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def list_workflows_sqlalchemy_core(self, **filters) -> List[Dict]:
        """SQLAlchemy Core query building + asyncpg execution with proper parameter binding"""
        # Build query using SQLAlchemy Core
        stmt = select(
            workflow_executions.c.id,
            workflow_executions.c.workflow_type,
            workflow_executions.c.current_step,
            workflow_executions.c.status,
            workflow_executions.c.updated_at
        )

        # Add filters
        if 'status' in filters:
            stmt = stmt.where(workflow_executions.c.status == filters['status'])
        if 'workflow_type' in filters:
            stmt = stmt.where(workflow_executions.c.workflow_type == filters['workflow_type'])

        # Order and limit
        stmt = stmt.order_by(workflow_executions.c.updated_at.desc())
        stmt = stmt.limit(filters.get('limit', 100))

        # Execute via asyncpg with proper parameter binding
        async with self.provider.pool.acquire() as conn:
            # Compile to PostgreSQL SQL with parameters
            compiled = stmt.compile(dialect=postgresql.dialect())

            # Get query text with %(param)s placeholders
            query_str = str(compiled)

            # Get parameter values in correct order
            params = list(compiled.params.values())

            rows = await conn.fetch(query_str, *params)
            return [dict(row) for row in rows]

    async def benchmark_method(self, name: str, method, iterations: int = 30, **kwargs):
        """Benchmark a method"""
        times = []

        for _ in range(iterations):
            start = time.perf_counter()
            await method(**kwargs)
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        self.results[name] = {
            'mean_ms': statistics.mean(times) * 1000,
            'median_ms': statistics.median(times) * 1000,
            'p95_ms': self._percentile(times, 0.95) * 1000,
            'p99_ms': self._percentile(times, 0.99) * 1000,
            'ops_per_sec': len(times) / sum(times) if sum(times) > 0 else 0,
        }

    def _percentile(self, data: List[float], percentile: float) -> float:
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile)
        return sorted_data[min(index, len(sorted_data) - 1)]

    def print_comparison(self):
        """Print comparison results"""
        print("\n" + "="*70)
        print("  PERFORMANCE COMPARISON: Raw SQL vs SQLAlchemy Core")
        print("="*70 + "\n")

        raw_sql = self.results.get('raw_sql')
        sqlalchemy = self.results.get('sqlalchemy_core')

        if not raw_sql or not sqlalchemy:
            print("Missing benchmark results")
            return

        print(f"{'Metric':<20} {'Raw SQL':>15} {'SQLAlchemy':>15} {'Difference':>15}")
        print("-"*70)

        metrics = ['mean_ms', 'median_ms', 'p95_ms', 'p99_ms', 'ops_per_sec']
        labels = ['Mean', 'Median', 'P95', 'P99', 'Throughput']

        for metric, label in zip(metrics, labels):
            raw_val = raw_sql[metric]
            sqlalchemy_val = sqlalchemy[metric]

            if metric == 'ops_per_sec':
                diff_pct = ((sqlalchemy_val - raw_val) / raw_val * 100) if raw_val > 0 else 0
                print(f"{label:<20} {raw_val:>12.1f} ops {sqlalchemy_val:>12.1f} ops {diff_pct:>+12.1f}%")
            else:
                diff_pct = ((sqlalchemy_val - raw_val) / raw_val * 100) if raw_val > 0 else 0
                print(f"{label:<20} {raw_val:>12.3f} ms {sqlalchemy_val:>12.3f} ms {diff_pct:>+12.1f}%")

        # Overall assessment
        print("\n" + "="*70)
        mean_degradation = ((sqlalchemy['mean_ms'] - raw_sql['mean_ms']) / raw_sql['mean_ms'] * 100)

        if abs(mean_degradation) < 5:
            verdict = "✓ PASS - Performance within 5% (EXCELLENT)"
        elif abs(mean_degradation) < 10:
            verdict = "✓ PASS - Performance within 10% (ACCEPTABLE)"
        else:
            verdict = "✗ FAIL - Performance degradation > 10%"

        print(f"  Go/No-Go Decision: {verdict}")
        print(f"  Mean Latency Impact: {mean_degradation:+.1f}%")
        print("="*70 + "\n")


async def main():
    print("="*70)
    print("  PHASE 3: SQLAlchemy Core Hybrid Approach Benchmark")
    print("="*70)
    print()

    # Connect
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
        await provider.save_workflow(wf_id, workflow_data)

    print(f"✓ Created {len(workflow_ids)} test workflows\n")

    # Run benchmarks
    benchmark = HybridBenchmark(provider)

    print("Benchmarking Raw SQL approach...")
    await benchmark.benchmark_method(
        'raw_sql',
        benchmark.list_workflows_raw_sql,
        iterations=50,
        status='ACTIVE',
        limit=50
    )

    print("Benchmarking SQLAlchemy Core approach...")
    await benchmark.benchmark_method(
        'sqlalchemy_core',
        benchmark.list_workflows_sqlalchemy_core,
        iterations=50,
        status='ACTIVE',
        limit=50
    )

    # Print results
    benchmark.print_comparison()

    # Cleanup
    print("Cleaning up test data...")
    async with provider.pool.acquire() as conn:
        await conn.execute("DELETE FROM workflow_executions WHERE workflow_type = 'BenchmarkWorkflow'")

    await provider.close()
    print("✓ Benchmark complete!\n")


if __name__ == '__main__':
    asyncio.run(main())
