"""
telemetry_steps.py — Step functions for the EdgeTelemetry workflow.

Signature: (state: TelemetryState, context: StepContext, **kw) -> dict
Bound to the workflow YAML via dotted path: telemetry_steps.<function_name>
"""
import os
import time
import logging
from typing import List

from pydantic import BaseModel, Field
import httpx

logger = logging.getLogger(__name__)


class TelemetryState(BaseModel):
    # Set at workflow start
    device_id: str = ""
    cloud_url: str = ""
    db_path: str = ""
    cycle: int = 0
    # Collected metrics
    cpu_percent: float = 0.0
    mem_percent: float = 0.0
    disk_percent: float = 0.0
    net_bytes_sent: int = 0
    net_bytes_recv: int = 0
    uptime_seconds: float = 0.0
    load_avg_1m: float = 0.0
    # Analysis
    health_status: str = "UNKNOWN"
    alerts: List[str] = Field(default_factory=list)
    # Sync state
    is_online: bool = False
    synced: bool = False
    saf_queue_depth: int = 0
    # DB stats
    db_size_bytes: int = 0
    workflow_count: int = 0
    audit_count: int = 0
    growth_rate_mb_day: float = 0.0


def collect_telemetry(state, context, **kw) -> dict:
    """Step 1: Collect system metrics via psutil (or simulate if unavailable)."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        net = psutil.net_io_counters()
        uptime = time.time() - psutil.boot_time()
        load = os.getloadavg()[0] if hasattr(os, 'getloadavg') else 0.0
    except ImportError:
        import random
        cpu = random.uniform(5, 40)
        mem = random.uniform(20, 60)
        disk = random.uniform(10, 50)

        class _Net:
            bytes_sent = random.randint(100_000, 1_000_000)
            bytes_recv = random.randint(100_000, 1_000_000)

        net = _Net()
        uptime = time.time() % 86400
        load = random.uniform(0.1, 2.0)

    return {
        "cpu_percent": cpu,
        "mem_percent": mem,
        "disk_percent": disk,
        "net_bytes_sent": net.bytes_sent,
        "net_bytes_recv": net.bytes_recv,
        "uptime_seconds": uptime,
        "load_avg_1m": load,
    }


def analyse_metrics(state, context, **kw) -> dict:
    """Step 2: Threshold checks; returns health_status + alerts list."""
    alerts = []
    if state.cpu_percent > 80:
        alerts.append(f"HIGH_CPU:{state.cpu_percent:.1f}%")
    if state.mem_percent > 90:
        alerts.append(f"HIGH_MEM:{state.mem_percent:.1f}%")
    if state.disk_percent > 90:
        alerts.append(f"LOW_DISK:{state.disk_percent:.1f}%used")
    health = "CRITICAL" if alerts else "NORMAL"
    return {"health_status": health, "alerts": alerts}


def sync_telemetry(state, context, **kw) -> dict:
    """Step 3: Probe cloud health endpoint; track SAF queue depth when offline."""
    is_online = False
    try:
        r = httpx.get(f"{state.cloud_url}/health", timeout=3.0)
        is_online = r.status_code == 200
    except Exception:
        pass

    saf_depth = state.saf_queue_depth
    if is_online:
        saf_depth = 0
        logger.info(f"[Telemetry] cycle={state.cycle} → ONLINE, SAF cleared")
    else:
        saf_depth += 1
        logger.warning(
            f"[Telemetry] cycle={state.cycle} → OFFLINE, SAF depth={saf_depth}"
        )

    return {"is_online": is_online, "synced": is_online, "saf_queue_depth": saf_depth}


def finalise_cycle(state, context, **kw) -> dict:
    """Step 4: Query SQLite for row counts, log summary, project DB growth."""
    db_path = state.db_path or os.getenv("DB_PATH", "/tmp/edge_sim.db")
    db_size = workflow_count = audit_count = 0

    try:
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    except OSError:
        pass

    try:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            workflow_count = conn.execute(
                "SELECT COUNT(*) FROM workflow_executions"
            ).fetchone()[0]
            audit_count = conn.execute(
                "SELECT COUNT(*) FROM workflow_audit_log"
            ).fetchone()[0]
    except Exception:
        pass

    interval = int(os.getenv("TELEMETRY_INTERVAL", "30"))
    cycles_per_day = 86400 / max(interval, 1)
    growth_rate_mb_day = (cycles_per_day * 5 * 1024) / (1024 * 1024)  # ~5 KB/workflow

    logger.info(
        f"[Cycle {state.cycle}] "
        f"CPU={state.cpu_percent:.1f}% MEM={state.mem_percent:.1f}% "
        f"DISK={state.disk_percent:.1f}% HEALTH={state.health_status} "
        f"ONLINE={state.is_online} SAF={state.saf_queue_depth} "
        f"DB={db_size // 1024}KB workflows={workflow_count} audit={audit_count} "
        f"~{growth_rate_mb_day:.1f}MB/day projected"
    )

    return {
        "db_size_bytes": db_size,
        "workflow_count": workflow_count,
        "audit_count": audit_count,
        "growth_rate_mb_day": growth_rate_mb_day,
    }
