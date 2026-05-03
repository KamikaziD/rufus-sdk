"""
CLI entry point for the NATS worker.

Usage:
    python -m ruvon.implementations.workers.nats_worker_cli --concurrency 4

Or via module invocation:
    python -m ruvon.workers.nats_worker --concurrency 4
"""
import asyncio
import argparse
import logging
import os
import signal


def main():
    parser = argparse.ArgumentParser(
        description="Ruvon NATS JetStream workflow worker",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--nats-url",
        default=os.getenv("RUVON_NATS_URL", "nats://localhost:4222"),
        help="NATS server URL",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("NATS_WORKER_CONCURRENCY", "4")),
        help="Maximum concurrent task executions",
    )
    parser.add_argument(
        "--registry",
        default=os.getenv("RUVON_WORKFLOW_REGISTRY_PATH", "config/workflow_registry.yaml"),
        help="Path to workflow_registry.yaml",
    )
    parser.add_argument(
        "--config-dir",
        default=os.getenv("RUVON_CONFIG_DIR", "config"),
        help="Directory containing workflow YAML files",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    from ruvon.implementations.workers.nats_worker import NATSWorker

    worker = NATSWorker(
        nats_url=args.nats_url,
        concurrency=args.concurrency,
        workflow_registry_path=args.registry,
        config_dir=args.config_dir,
    )

    loop = asyncio.get_event_loop()

    def _shutdown(*_):
        print("\n[NATSWorker] Shutting down...")
        loop.create_task(worker.stop())

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(worker.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
