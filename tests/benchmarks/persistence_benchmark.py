"""
Persistence Layer Performance Benchmarks

Compares SQLite vs PostgreSQL (if available) for common workflow operations.

Usage:
    python tests/benchmarks/persistence_benchmark.py
    python tests/benchmarks/persistence_benchmark.py --postgres postgres://user:pass@localhost/rufus_test
"""

import asyncio
import time
import argparse
import statistics
from typing import List, Dict, Any, Optional
from pathlib import Path
import tempfile
import os

from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider

# Try to import PostgreSQL provider
try:
    from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False


class BenchmarkResult:
    """Container for benchmark results"""

    def __init__(self, name: str):
        self.name = name
        self.times: List[float] = []

    def add_time(self, elapsed: float):
        """Add a timing measurement"""
        self.times.append(elapsed)

    def get_stats(self) -> Dict[str, float]:
        """Calculate statistics"""
        if not self.times:
            return {}

        return {
            'mean': statistics.mean(self.times),
            'median': statistics.median(self.times),
            'stdev': statistics.stdev(self.times) if len(self.times) > 1 else 0,
            'min': min(self.times),
            'max': max(self.times),
            'p95': self._percentile(self.times, 0.95),
            'p99': self._percentile(self.times, 0.99),
            'ops_per_sec': len(self.times) / sum(self.times) if sum(self.times) > 0 else 0,
        }

    def _percentile(self, data: List[float], percentile: float) -> float:
        """Calculate percentile"""
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile)
        return sorted_data[min(index, len(sorted_data) - 1)]


class PersistenceBenchmark:
    """Performance benchmark suite for persistence providers"""

    def __init__(self, sqlite_provider, postgres_provider=None):
        self.sqlite = sqlite_provider
        self.postgres = postgres_provider
        self.results: Dict[str, Dict[str, BenchmarkResult]] = {
            'sqlite': {},
            'postgres': {}
        }

    async def setup_schema(self):
        """Set up database schema"""
        # SQLite schema
        await self.sqlite.conn.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_executions (
                id TEXT PRIMARY KEY,
                workflow_type TEXT NOT NULL,
                workflow_version TEXT NOT NULL DEFAULT 'v1',                             
                current_step INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT '{}',
                steps_config TEXT NOT NULL DEFAULT '[]',
                state_model_path TEXT NOT NULL,
                saga_mode INTEGER DEFAULT 0,
                completed_steps_stack TEXT DEFAULT '[]',
                parent_execution_id TEXT,
                blocked_on_child_id TEXT,
                data_region TEXT DEFAULT 'us-east-1',
                priority INTEGER DEFAULT 5,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                idempotency_key TEXT UNIQUE,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                execution_id TEXT NOT NULL,
                step_name TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                worker_id TEXT,
                claimed_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                last_error TEXT,
                task_data TEXT,
                result TEXT,
                idempotency_key TEXT UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS workflow_execution_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT NOT NULL,
                step_name TEXT,
                log_level TEXT NOT NULL,
                message TEXT NOT NULL,
                logged_at TEXT DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS workflow_metrics (
                metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT NOT NULL,
                workflow_type TEXT,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                unit TEXT,
                step_name TEXT,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                tags TEXT DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_workflow_status ON workflow_executions(status);
            CREATE INDEX IF NOT EXISTS idx_workflow_type ON workflow_executions(workflow_type);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        """)

    async def benchmark_save_workflow(self, provider_name: str, provider, iterations: int = 100):
        """Benchmark workflow save operations"""
        result = BenchmarkResult(f"{provider_name}_save_workflow")

        for i in range(iterations):
            workflow_data = {
                'id': f'workflow_{i}',
                'workflow_type': 'BenchmarkWorkflow',
                'current_step': 0,
                'status': 'ACTIVE',
                'state': {'iteration': i, 'data': {'key': f'value_{i}'}},
                'steps_config': [
                    {'name': 'Step1', 'type': 'STANDARD'},
                    {'name': 'Step2', 'type': 'ASYNC'},
                ],
                'state_model_path': 'benchmark.State',
            }

            start = time.perf_counter()
            await provider.save_workflow(f'workflow_{i}', workflow_data)
            elapsed = time.perf_counter() - start
            result.add_time(elapsed)

        self.results[provider_name]['save_workflow'] = result

    async def benchmark_load_workflow(self, provider_name: str, provider, iterations: int = 100):
        """Benchmark workflow load operations"""
        result = BenchmarkResult(f"{provider_name}_load_workflow")

        for i in range(iterations):
            start = time.perf_counter()
            await provider.load_workflow(f'workflow_{i}')
            elapsed = time.perf_counter() - start
            result.add_time(elapsed)

        self.results[provider_name]['load_workflow'] = result

    async def benchmark_list_workflows(self, provider_name: str, provider, iterations: int = 50):
        """Benchmark workflow list operations"""
        result = BenchmarkResult(f"{provider_name}_list_workflows")

        for _ in range(iterations):
            start = time.perf_counter()
            await provider.list_workflows(limit=100)
            elapsed = time.perf_counter() - start
            result.add_time(elapsed)

        self.results[provider_name]['list_workflows'] = result

    async def benchmark_create_task(self, provider_name: str, provider, iterations: int = 100):
        """Benchmark task creation"""
        result = BenchmarkResult(f"{provider_name}_create_task")

        for i in range(iterations):
            start = time.perf_counter()
            await provider.create_task_record(
                execution_id=f'workflow_{i % 100}',
                step_name='BenchmarkStep',
                step_index=0,
                task_data={'iteration': i}
            )
            elapsed = time.perf_counter() - start
            result.add_time(elapsed)

        self.results[provider_name]['create_task'] = result

    async def benchmark_log_execution(self, provider_name: str, provider, iterations: int = 200):
        """Benchmark execution logging"""
        result = BenchmarkResult(f"{provider_name}_log_execution")

        for i in range(iterations):
            start = time.perf_counter()
            await provider.log_execution(
                workflow_id=f'workflow_{i % 100}',
                log_level='INFO',
                message=f'Benchmark log message {i}',
                step_name='BenchmarkStep'
            )
            elapsed = time.perf_counter() - start
            result.add_time(elapsed)

        self.results[provider_name]['log_execution'] = result

    async def benchmark_record_metric(self, provider_name: str, provider, iterations: int = 200):
        """Benchmark metric recording"""
        result = BenchmarkResult(f"{provider_name}_record_metric")

        for i in range(iterations):
            start = time.perf_counter()
            await provider.record_metric(
                workflow_id=f'workflow_{i % 100}',
                workflow_type='BenchmarkWorkflow',
                metric_name='step_duration_ms',
                metric_value=float(i % 1000),
                unit='ms',
                step_name='BenchmarkStep'
            )
            elapsed = time.perf_counter() - start
            result.add_time(elapsed)

        self.results[provider_name]['record_metric'] = result

    async def run_all_benchmarks(self):
        """Run all benchmarks"""
        print("Setting up schemas...")
        await self.setup_schema()

        providers = [('sqlite', self.sqlite)]
        if self.postgres:
            providers.append(('postgres', self.postgres))

        for provider_name, provider in providers:
            print(f"\n{'='*70}")
            print(f"  Running benchmarks for {provider_name.upper()}")
            print(f"{'='*70}\n")

            print(f"  → Benchmarking save_workflow...")
            await self.benchmark_save_workflow(provider_name, provider, iterations=100)

            print(f"  → Benchmarking load_workflow...")
            await self.benchmark_load_workflow(provider_name, provider, iterations=100)

            print(f"  → Benchmarking list_workflows...")
            await self.benchmark_list_workflows(provider_name, provider, iterations=50)

            print(f"  → Benchmarking create_task...")
            await self.benchmark_create_task(provider_name, provider, iterations=100)

            print(f"  → Benchmarking log_execution...")
            await self.benchmark_log_execution(provider_name, provider, iterations=200)

            print(f"  → Benchmarking record_metric...")
            await self.benchmark_record_metric(provider_name, provider, iterations=200)

            print(f"  ✓ Completed {provider_name} benchmarks")

    def print_results(self):
        """Print benchmark results"""
        print(f"\n{'='*70}")
        print(f"  BENCHMARK RESULTS")
        print(f"{'='*70}\n")

        # Get all operation names
        operations = set()
        for provider_results in self.results.values():
            operations.update(provider_results.keys())

        for operation in sorted(operations):
            print(f"\n{operation.upper().replace('_', ' ')}")
            print("-" * 70)

            headers = [
                "Provider", "Mean (ms)", "Median (ms)", "P95 (ms)", "P99 (ms)", "Ops/sec"]
            print(
                f"{'Provider':<12} {'Mean':<12} {'Median':<12} {'P95':<12} {'P99':<12} {'Ops/sec':<10}")
            print("-" * 70)

            for provider_name in ['sqlite', 'postgres']:
                if provider_name not in self.results:
                    continue

                if operation not in self.results[provider_name]:
                    continue

                stats = self.results[provider_name][operation].get_stats()
                print(
                    f"{provider_name:<12} "
                    f"{stats['mean']*1000:>10.3f}  "
                    f"{stats['median']*1000:>10.3f}  "
                    f"{stats['p95']*1000:>10.3f}  "
                    f"{stats['p99']*1000:>10.3f}  "
                    f"{stats['ops_per_sec']:>10.1f}"
                )

        # Summary comparison
        if 'postgres' in self.results and 'sqlite' in self.results:
            print(f"\n{'='*70}")
            print(f"  PERFORMANCE COMPARISON (SQLite vs PostgreSQL)")
            print(f"{'='*70}\n")

            for operation in sorted(operations):
                if operation not in self.results['sqlite'] or operation not in self.results['postgres']:
                    continue

                sqlite_stats = self.results['sqlite'][operation].get_stats()
                postgres_stats = self.results['postgres'][operation].get_stats(
                )

                if postgres_stats['mean'] > 0:
                    speedup = postgres_stats['mean'] / sqlite_stats['mean']
                    if speedup > 1:
                        print(
                            f"  {operation:<25} SQLite is {speedup:.2f}x faster")
                    else:
                        print(
                            f"  {operation:<25} PostgreSQL is {1/speedup:.2f}x faster")


async def main():
    parser = argparse.ArgumentParser(
        description='Persistence layer benchmarks')
    parser.add_argument(
        '--postgres',
        help='PostgreSQL connection URL (e.g., postgresql://user:pass@localhost/test)'
    )
    parser.add_argument(
        '--iterations',
        type=int,
        default=100,
        help='Number of iterations for each benchmark (default: 100)'
    )

    args = parser.parse_args()

    # Set up SQLite (in-memory for fair comparison)
    print("Initializing SQLite provider (in-memory)...")
    sqlite_provider = SQLitePersistenceProvider(db_path=":memory:")
    await sqlite_provider.initialize()

    # Set up PostgreSQL if URL provided
    postgres_provider = None
    if args.postgres and POSTGRES_AVAILABLE:
        print(f"Initializing PostgreSQL provider...")
        postgres_provider = PostgresPersistenceProvider(db_url=args.postgres)
        try:
            await postgres_provider.initialize()
        except Exception as e:
            print(f"Warning: Could not connect to PostgreSQL: {e}")
            print("Running SQLite-only benchmarks...")
            postgres_provider = None
    elif args.postgres and not POSTGRES_AVAILABLE:
        print("Warning: PostgreSQL provider not available (asyncpg not installed)")
        print("Running SQLite-only benchmarks...")
    else:
        print("Running SQLite-only benchmarks (no --postgres URL provided)")

    # Run benchmarks
    benchmark = PersistenceBenchmark(sqlite_provider, postgres_provider)
    await benchmark.run_all_benchmarks()

    # Print results
    benchmark.print_results()

    # Cleanup
    await sqlite_provider.close()
    if postgres_provider:
        await postgres_provider.close()


if __name__ == '__main__':
    asyncio.run(main())
