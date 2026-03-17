"""
edge_device_sim.py — Rufus edge device emulator for docker-compose testing.

1. Registers the device with the cloud control plane.
2. Starts RufusEdgeAgent (heartbeat + config polling).
3. Runs a continuous EdgeTelemetry workflow loop (TELEMETRY_INTERVAL seconds).
4. Runs a concurrent PaymentSimulation workflow loop (PAYMENT_INTERVAL seconds).
   Each payment triggers an inline TransactionMonitoring sub-workflow (fraud screening).
5. Gracefully shuts down on SIGTERM / SIGINT.

Environment variables:
    CLOUD_URL             Cloud control plane URL (default: http://rufus-server:8000)
    DEVICE_ID             Unique device identifier (default: sim-device-001)
    DEVICE_TYPE           "pos" or "atm" — controls payment amounts and fraud rules (default: pos)
    FLOOR_LIMIT           Offline approval floor limit in USD (default: 1000.0 for POS, 500 for ATM)
    RUFUS_API_KEY         API key returned after registration (leave blank; set after register)
    RUFUS_ENCRYPTION_KEY  Encryption key for workflow state (optional)
    DB_PATH               SQLite database path (default: /tmp/edge_sim.db)
    RUFUS_REGISTRATION_KEY  Key required for /api/v1/devices/register (default: test-registration-key)
    TELEMETRY_INTERVAL    Seconds between telemetry cycles (default: 30)
    PAYMENT_INTERVAL      Seconds between payment simulation cycles (default: 20)
    EDGE_WORKFLOW_SYNC    Push completed workflows to cloud + purge SQLite (default: true)
"""

import asyncio
import logging
import os
import signal
import sys

import httpx

# Resolve step modules from the same directory as this script
sys.path.insert(0, os.path.dirname(__file__))

import payment_sim_steps      # noqa: E402  (after sys.path patch)
import txn_monitoring_steps  # noqa: E402  (registers velocity tracker, etc.)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("edge-sim")

CLOUD_URL = os.getenv("CLOUD_URL", "http://rufus-server:8000")
DEVICE_ID = os.getenv("DEVICE_ID", "sim-device-001")
DEVICE_TYPE = os.getenv("DEVICE_TYPE", "pos")   # "pos" or "atm"
# Default floor limit: $1000 for POS, $500 for ATM
_default_floor = "500.0" if DEVICE_TYPE == "atm" else "1000.0"
FLOOR_LIMIT = float(os.getenv("FLOOR_LIMIT", _default_floor))
DB_PATH = os.getenv("DB_PATH", "/tmp/edge_sim.db")
ENCRYPTION_KEY = os.getenv("RUFUS_ENCRYPTION_KEY", "") or None
REGISTRATION_KEY = os.getenv("RUFUS_REGISTRATION_KEY", "test-registration-key")
TELEMETRY_INTERVAL = int(os.getenv("TELEMETRY_INTERVAL", "30"))
PAYMENT_INTERVAL = int(os.getenv("PAYMENT_INTERVAL", "20"))
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


PAYMENT_SIM_YAML = """
workflow_type: "PaymentSimulation"
workflow_version: "1.1.0"
description: "Simulated card payment — online approval or offline SAF + fraud screening"
initial_state_model_path: "payment_sim_steps.PaymentSimState"

steps:
  - name: "Generate_Payment"
    type: "STANDARD"
    function: "payment_sim_steps.generate_payment"
    description: "Generate random card payment data"
    automate_next: true

  - name: "Check_Connectivity"
    type: "STANDARD"
    function: "payment_sim_steps.check_connectivity"
    description: "Simulate connectivity check — 70% online, 30% offline"

  - name: "Authorize_Online"
    type: "STANDARD"
    function: "payment_sim_steps.authorize_online"
    description: "Simulate gateway approval (online path)"

  - name: "Check_Floor_Limit"
    type: "STANDARD"
    function: "payment_sim_steps.check_floor_limit"
    description: "Route by floor limit (offline path)"

  - name: "Approve_Offline"
    type: "STANDARD"
    function: "payment_sim_steps.approve_offline"
    description: "Approve offline and queue into SAF"

  - name: "Decline_Payment"
    type: "STANDARD"
    function: "payment_sim_steps.decline_payment"
    description: "Decline — exceeds offline floor limit"
    automate_next: true

  - name: "Launch_Monitoring"
    type: "STANDARD"
    function: "payment_sim_steps.launch_monitoring"
    description: "Run TransactionMonitoring fraud screening sub-workflow"
    automate_next: true

  - name: "Complete_Payment"
    type: "STANDARD"
    function: "payment_sim_steps.complete_payment"
    description: "Log final outcome"
"""


TRANSACTION_MONITORING_YAML = """
workflow_type: "TransactionMonitoring"
workflow_version: "1.0.0"
description: "Tazama-inspired rule + typology + WASM ML fraud screening — POS and ATM"
initial_state_model_path: "txn_monitoring_steps.TransactionMonitoringState"

steps:
  - name: "Extract_Features"
    type: "STANDARD"
    function: "txn_monitoring_steps.extract_features"
    description: "Build normalised feature vector for ML scoring"
    automate_next: true

  - name: "Route_By_Type"
    type: "STANDARD"
    function: "txn_monitoring_steps.route_by_type"
    description: "Route to POS or ATM rule evaluation"

  - name: "POS_Rules"
    type: "STANDARD"
    function: "txn_monitoring_steps.evaluate_pos_rules"
    description: "POS fraud rules: velocity, micro-structuring, card-testing (5 rules)"

  - name: "ATM_Rules"
    type: "STANDARD"
    function: "txn_monitoring_steps.evaluate_atm_rules"
    description: "ATM fraud rules: large-cash, after-hours, structuring (5 rules)"
    automate_next: true

  - name: "Score_With_Wasm"
    type: "STANDARD"
    function: "txn_monitoring_steps.score_with_wasm"
    description: "Rust logistic regression via Wasmtime WASI (Python fallback)"
    automate_next: true

  - name: "Apply_Typologies"
    type: "STANDARD"
    function: "txn_monitoring_steps.apply_typologies"
    description: "Map rule combinations to named fraud typologies"
    automate_next: true

  - name: "Monitoring_Verdict"
    type: "STANDARD"
    function: "txn_monitoring_steps.monitoring_verdict"
    description: "Classify risk tier; jump to Flag_Transaction for HIGH/CRITICAL"
    automate_next: true

  - name: "Flag_Transaction"
    type: "STANDARD"
    function: "txn_monitoring_steps.flag_transaction"
    description: "Create alert record for HIGH/CRITICAL; log PASS otherwise"
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
        device_name = (
            f"ATM Device {DEVICE_ID}" if DEVICE_TYPE == "atm"
            else f"POS Device {DEVICE_ID}"
        )
        resp = await client.post(
            "/api/v1/devices/register",
            json={
                "device_id": DEVICE_ID,
                "device_type": DEVICE_TYPE,
                "device_name": device_name,
                "merchant_id": "test-merchant-001",
                "firmware_version": "1.0.0",
                "sdk_version": "1.0.0rc4",
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


async def _register_payment_workflow(agent):
    """Inject PaymentSimulation YAML into the WorkflowBuilder via the config cache."""
    ok = await agent.config_manager.handle_update_workflow_command(
        {
            "workflow_type": "PaymentSimulation",
            "yaml_content": PAYMENT_SIM_YAML.strip(),
            "version": "1.1.0",
        },
        workflow_builder=agent.workflow_builder,
    )
    logger.info(
        f"PaymentSimulation workflow registered (cached in edge_workflow_cache): {ok}"
    )


async def _register_monitoring_workflow(agent):
    """Inject TransactionMonitoring YAML into the WorkflowBuilder via the config cache."""
    ok = await agent.config_manager.handle_update_workflow_command(
        {
            "workflow_type": "TransactionMonitoring",
            "yaml_content": TRANSACTION_MONITORING_YAML.strip(),
            "version": "1.0.0",
        },
        workflow_builder=agent.workflow_builder,
    )
    logger.info(
        f"TransactionMonitoring workflow registered (cached in edge_workflow_cache): {ok}"
    )


async def payment_loop(agent):
    """Continuously run PaymentSimulation workflow, pausing PAYMENT_INTERVAL between cycles."""
    cycle = 0
    logger.info(
        f"Payment loop started (interval={PAYMENT_INTERVAL}s, device_type={DEVICE_TYPE}, "
        f"floor_limit=${FLOOR_LIMIT:.0f}). "
        "Generating randomised card payments — 70% online / 30% offline SAF + fraud screening."
    )
    while not _shutdown_event.is_set():
        cycle += 1
        logger.info(f"─── Payment cycle {cycle} ───")
        await _run_workflow_direct(agent, "PaymentSimulation", {
            "device_id": DEVICE_ID,
            "device_type": DEVICE_TYPE,
            "floor_limit": FLOOR_LIMIT,
            "cloud_url": CLOUD_URL,
            "db_path": DB_PATH,
            "cycle": cycle,
        })
        try:
            await asyncio.wait_for(
                _shutdown_event.wait(), timeout=float(PAYMENT_INTERVAL)
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

    # Always PATCH sdk_version on startup so restarts refresh the DB value
    if api_key:
        try:
            async with httpx.AsyncClient(base_url=CLOUD_URL, timeout=10) as client:
                await client.patch(
                    f"/api/v1/devices/{DEVICE_ID}",
                    json={"sdk_version": "1.0.0rc4"},
                    headers={"X-API-Key": api_key},
                )
        except Exception as e:
            logger.warning(f"Could not PATCH sdk_version: {e}")

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

    # Wire module-level references for payment step functions
    payment_sim_steps._sync_manager = agent.sync_manager
    payment_sim_steps._agent = agent          # for launch_monitoring inline sub-workflow

    # Register HITL fraud review command handler
    async def _handle_resume_fraud_review(cmd_data: dict) -> None:
        alert_id = cmd_data.get("alert_id", "")
        if not alert_id:
            logger.warning("resume_fraud_review missing alert_id")
            return
        txn_monitoring_steps._pending_fraud_decisions[alert_id] = {
            "decision": cmd_data.get("decision", "APPROVE"),
            "reviewer_notes": cmd_data.get("reviewer_notes", ""),
        }
        logger.info(
            "resume_fraud_review: alert=%s decision=%s",
            alert_id, cmd_data.get("decision"),
        )

    agent.register_command_handler("resume_fraud_review", _handle_resume_fraud_review)

    # Register embedded workflow definitions
    await _register_payment_workflow(agent)
    await _register_monitoring_workflow(agent)

    try:
        await asyncio.gather(
            telemetry_loop(agent),
            payment_loop(agent),
        )
    finally:
        await agent.stop()
        logger.info("Edge sim stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
