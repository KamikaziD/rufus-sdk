"""
edge_device_sim.py — Rufus edge device emulator for docker-compose testing.

1. Registers the device with the cloud control plane.
2. Starts RufusEdgeAgent (heartbeat + config polling).
3. Runs a continuous EdgeTelemetry workflow loop (TELEMETRY_INTERVAL seconds).
4. Gracefully shuts down on SIGTERM / SIGINT.

Environment variables:
    CLOUD_URL             Cloud control plane URL (default: http://rufus-server:8000)
    DEVICE_ID             Unique device identifier (default: sim-device-001)
    RUFUS_API_KEY         API key returned after registration (leave blank; set after register)
    RUFUS_ENCRYPTION_KEY  Encryption key for workflow state (optional)
    DB_PATH               SQLite database path (default: /tmp/edge_sim.db)
    RUFUS_REGISTRATION_KEY  Key required for /api/v1/devices/register (default: test-registration-key)
    TELEMETRY_INTERVAL    Seconds between telemetry cycles (default: 30)
    EDGE_WORKFLOW_SYNC    Push completed workflows to cloud + purge SQLite (default: true)
"""

import asyncio
import logging
import os
import signal

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("edge-sim")

CLOUD_URL = os.getenv("CLOUD_URL", "http://rufus-server:8000")
DEVICE_ID = os.getenv("DEVICE_ID", "sim-device-001")
DB_PATH = os.getenv("DB_PATH", "/tmp/edge_sim.db")
ENCRYPTION_KEY = os.getenv("RUFUS_ENCRYPTION_KEY", "") or None
REGISTRATION_KEY = os.getenv("RUFUS_REGISTRATION_KEY", "test-registration-key")
TELEMETRY_INTERVAL = int(os.getenv("TELEMETRY_INTERVAL", "30"))
EDGE_WORKFLOW_SYNC = os.getenv("EDGE_WORKFLOW_SYNC", "true").lower() == "true"

# Persist API key alongside the SQLite DB so it survives container restarts
_API_KEY_FILE = DB_PATH + ".apikey"

# Graceful shutdown event
_shutdown_event = asyncio.Event()


def _handle_signal(sig, frame):
    logger.info(f"Signal {sig} received — stopping telemetry loop gracefully")
    _shutdown_event.set()


EDGE_TELEMETRY_YAML = """
workflow_type: "EdgeTelemetry"
workflow_version: "1.0.0"
description: "Continuous system telemetry for edge device health monitoring"
initial_state_model_path: "telemetry_steps.TelemetryState"

steps:
  - name: "Collect_Telemetry"
    type: "STANDARD"
    function: "telemetry_steps.collect_telemetry"
    description: "Gather CPU/memory/disk/network metrics"
    automate_next: true

  - name: "Analyse_Metrics"
    type: "STANDARD"
    function: "telemetry_steps.analyse_metrics"
    description: "Check thresholds and classify device health"
    automate_next: true

  - name: "Sync_Telemetry"
    type: "STANDARD"
    function: "telemetry_steps.sync_telemetry"
    description: "Report to cloud if online; track SAF queue depth if offline"
    automate_next: true

  - name: "Finalise_Cycle"
    type: "STANDARD"
    function: "telemetry_steps.finalise_cycle"
    description: "Log cycle summary and DB growth projections"
"""


async def register_device() -> str:
    """
    Register the device with the cloud control plane.

    Returns the api_key (from server on first registration, or from local
    cache on subsequent starts). The server only returns the key once, so
    we persist it to _API_KEY_FILE for use across restarts.
    """
    # Load cached key if available (device already registered and key persisted)
    try:
        with open(_API_KEY_FILE) as f:
            cached = f.read().strip()
        if cached:
            logger.info(f"Loaded persisted API key for {DEVICE_ID}")
            return cached
    except FileNotFoundError:
        pass

    async with httpx.AsyncClient(base_url=CLOUD_URL, timeout=15) as client:
        resp = await client.post(
            "/api/v1/devices/register",
            json={
                "device_id": DEVICE_ID,
                "device_type": "sim",
                "device_name": f"Sim Device {DEVICE_ID}",
                "merchant_id": "test-merchant-001",
                "firmware_version": "1.0.0",
                "sdk_version": "0.7.7",
                "capabilities": ["workflow_execution", "update_workflow"],
            },
            headers={"X-Registration-Key": REGISTRATION_KEY},
        )

        if resp.status_code in (200, 201):
            data = resp.json()
            api_key = data.get("api_key", "")
            logger.info(f"Device registered: {DEVICE_ID}  api_key={api_key[:8]}...")
            # Persist for future restarts
            try:
                with open(_API_KEY_FILE, "w") as f:
                    f.write(api_key)
            except OSError as e:
                logger.warning(f"Could not persist API key: {e}")
            return api_key

        if resp.status_code == 400 and "already registered" in resp.text:
            logger.warning(
                f"Device {DEVICE_ID} already registered but no local key file found — "
                "config endpoint will 401 until the device is re-registered"
            )
            return ""

        logger.warning(f"Registration returned {resp.status_code}: {resp.text}")
        return ""


async def _register_telemetry_workflow(agent):
    """Inject EdgeTelemetry YAML into the WorkflowBuilder via the config cache."""
    ok = await agent.config_manager.handle_update_workflow_command(
        {
            "workflow_type": "EdgeTelemetry",
            "yaml_content": EDGE_TELEMETRY_YAML.strip(),
            "version": "1.0.0",
        },
        workflow_builder=agent.workflow_builder,
    )
    logger.info(
        f"EdgeTelemetry workflow registered (cached in edge_workflow_cache): {ok}"
    )


async def _run_workflow_direct(agent, workflow_type: str, data: dict) -> dict:
    """
    Run a workflow to completion, bypassing the config_manager.get_workflow_config()
    check that only knows about DeviceConfig.workflows (cloud-polled definitions).

    Workflows registered via handle_update_workflow_command() live in
    workflow_builder._workflow_configs, which create_workflow() looks up directly.
    """
    from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
    from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

    workflow = await agent.workflow_builder.create_workflow(
        workflow_type=workflow_type,
        persistence_provider=agent.persistence,
        execution_provider=agent.executor,
        workflow_builder=agent.workflow_builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=agent.observer,
        initial_data=data,
        owner_id=agent.device_id,
    )

    try:
        while workflow.status not in (
            "COMPLETED", "FAILED", "CANCELLED", "FAILED_ROLLED_BACK"
        ):
            await workflow.next_step(user_input={})

        return {
            "workflow_id": workflow.id,
            "status": workflow.status,
            "state": (
                workflow.state.model_dump()
                if hasattr(workflow.state, "model_dump")
                else {}
            ),
        }
    except Exception as exc:
        logger.error(f"Workflow {workflow_type} failed: {exc}")
        return {
            "workflow_id": getattr(workflow, "id", "?"),
            "status": "FAILED",
            "error": str(exc),
        }


async def telemetry_loop(agent):
    """Continuously run EdgeTelemetry workflow, pausing TELEMETRY_INTERVAL between cycles."""
    cycle = 0
    logger.info(
        f"Telemetry loop started (interval={TELEMETRY_INTERVAL}s). "
        "Stop container or cut network to emulate disconnection / power failure."
    )
    while not _shutdown_event.is_set():
        cycle += 1
        logger.info(f"─── Telemetry cycle {cycle} ───")
        await _run_workflow_direct(agent, "EdgeTelemetry", {
            "device_id": DEVICE_ID,
            "cloud_url": CLOUD_URL,
            "db_path": DB_PATH,
            "cycle": cycle,
        })
        try:
            await asyncio.wait_for(
                _shutdown_event.wait(), timeout=float(TELEMETRY_INTERVAL)
            )
        except asyncio.TimeoutError:
            pass


async def main():
    # Wait for server to be reachable
    for attempt in range(20):
        try:
            async with httpx.AsyncClient(base_url=CLOUD_URL, timeout=5) as client:
                resp = await client.get("/health")
                if resp.status_code == 200:
                    logger.info("Cloud control plane is healthy")
                    break
        except Exception as exc:
            logger.info(f"Waiting for cloud ({attempt + 1}/20): {exc}")
            await asyncio.sleep(5)
    else:
        logger.error("Cloud control plane did not become healthy — exiting")
        raise SystemExit(1)

    api_key = await register_device()

    from rufus_edge import RufusEdgeAgent

    agent = RufusEdgeAgent(
        device_id=DEVICE_ID,
        cloud_url=CLOUD_URL,
        api_key=api_key,
        db_path=DB_PATH,
        encryption_key=ENCRYPTION_KEY,
        heartbeat_interval=30,    # poll for commands every 30 s
        config_poll_interval=60,
        sync_interval=60,
        workflow_sync_enabled=EDGE_WORKFLOW_SYNC,
    )

    await agent.start()
    logger.info("Edge agent running — starting telemetry loop...")

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    await _register_telemetry_workflow(agent)

    try:
        await telemetry_loop(agent)
    finally:
        await agent.stop()
        logger.info("Edge sim stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
