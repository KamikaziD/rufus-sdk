# **RUFUS SDK PHASE 1 PERFORMANCE BENCHMARKS**
  
    Optimizations Enabled:
        - Serialization Backend: json (stdlib)
        - Event Loop Backend: asyncio (stdlib)
        - Import Caching: Enabled

## **[1/4] Benchmarking JSON Serialization...**

### JSON Serialization Performance

    iterations                    : 10000
    serialize_time_ms             : 28.53
    serialize_ops_per_sec         : 350,504.15
    deserialize_time_ms           : 21.21
    deserialize_ops_per_sec       : 471,485.90
    backend                       : json (stdlib)


## **[2/4] Benchmarking Import Caching...**

### Import Caching Performance

    iterations                    : 1000
    first_import_ms               : 0.03
    cached_import_avg_ms          : 0.00
    speedup                       : 249.38
    cache_size                    : 1

## **[3/4] Benchmarking Async Overhead...**

### Async/Await Overhead

    iterations                    : 1000
    avg_latency_us                : 15.69
    p50_latency_us                : 14.58
    p95_latency_us                : 23.29
    p99_latency_us                : 34.41
    event_loop_type               : _UnixSelectorEventLoop

## **[4/4] Benchmarking Workflow Throughput...**

### Workflow Execution Throughput

    num_workflows                 : 1000
    elapsed_seconds               : 0.00
    throughput_per_sec            : 905,147.76
    avg_latency_ms                : 0.00

## SUMMARY

    Serialization: 350,504 ops/sec (json (stdlib))
    Import Cache: 249.4x speedup
    Async Latency: 14.6µs (p50), 34.4µs (p99)
    Workflow Throughput: 905,148 workflows/sec
