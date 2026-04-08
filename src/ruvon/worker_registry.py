import os
import time
import threading
import json
import socket
import logging
import signal
import subprocess
import psycopg2
from datetime import datetime, timezone

try:
    import ruvon
    _SDK_VERSION = ruvon.__version__
except Exception:
    _SDK_VERSION = "unknown"

logger = logging.getLogger(__name__)


class WorkerRegistry:
    def __init__(self, db_url: str, celery_app=None, heartbeat_interval: int = 30):
        self.db_url = db_url
        self.celery_app = celery_app
        self.heartbeat_interval = heartbeat_interval
        self.hostname = socket.gethostname()
        self.worker_id = os.getenv("WORKER_ID", f"worker-{self.hostname}")
        self.region = os.getenv("WORKER_REGION", "default")
        self.zone = os.getenv("WORKER_ZONE", "default")
        self.capabilities = json.loads(os.getenv("WORKER_CAPABILITIES", "{}"))
        self.sdk_version = _SDK_VERSION
        self._stop_event = threading.Event()
        self._heartbeat_thread = None

    def _get_connection(self):
        return psycopg2.connect(self.db_url)

    def register(self, retries: int = 10, retry_delay: float = 5.0):
        """Register the worker in the database.

        Retries if the worker_nodes table doesn't exist yet (race with server migration).
        """
        for attempt in range(1, retries + 1):
            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            DELETE FROM worker_nodes
                            WHERE hostname = %s AND status = 'offline';
                        """, (self.hostname,))
                        cur.execute("""
                            INSERT INTO worker_nodes
                            (worker_id, hostname, region, zone, capabilities, status,
                             last_heartbeat, sdk_version)
                            VALUES (%s, %s, %s, %s, %s, 'online', NOW(), %s)
                            ON CONFLICT (worker_id)
                            DO UPDATE SET
                                status = 'online',
                                last_heartbeat = NOW(),
                                sdk_version = EXCLUDED.sdk_version,
                                updated_at = NOW();
                        """, (
                            self.worker_id,
                            self.hostname,
                            self.region,
                            self.zone,
                            json.dumps(self.capabilities),
                            self.sdk_version,
                        ))
                logger.info(f"Worker {self.worker_id} registered successfully in region {self.region}.")
                self._start_heartbeat()
                return
            except Exception as e:
                if "does not exist" in str(e) and attempt < retries:
                    logger.warning(
                        f"Worker registration attempt {attempt}/{retries} failed "
                        f"(table not ready yet), retrying in {retry_delay}s: {e}"
                    )
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Failed to register worker {self.worker_id}: {e}")

    def deregister(self):
        """Mark the worker as offline."""
        self._stop_event.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5.0)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE worker_nodes
                        SET status = 'offline', last_heartbeat = NOW()
                        WHERE worker_id = %s
                    """, (self.worker_id,))
            logger.info(f"Worker {self.worker_id} deregistered successfully.")
        except Exception as e:
            logger.error(f"Failed to deregister worker {self.worker_id}: {e}")

    def _start_heartbeat(self):
        """Start the heartbeat background thread."""
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self):
        """Tick every 1s; send heartbeat + poll commands every heartbeat_interval seconds."""
        logger.info(f"Worker {self.worker_id} heartbeat started (interval={self.heartbeat_interval}s).")
        tick_count = 0
        while not self._stop_event.is_set():
            if tick_count % self.heartbeat_interval == 0:
                try:
                    self._do_heartbeat_and_check_commands()
                except Exception as e:
                    logger.error(f"Worker {self.worker_id} heartbeat/command cycle failed: {e}")
            tick_count += 1
            time.sleep(1)
            if self._stop_event.is_set():
                break

    def _do_heartbeat_and_check_commands(self):
        """One psycopg2 connection: heartbeat UPDATE + atomically fetch+claim pending commands."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Heartbeat
                cur.execute("""
                    UPDATE worker_nodes
                    SET last_heartbeat = NOW()
                    WHERE worker_id = %s
                """, (self.worker_id,))

                # 2. Atomically fetch and claim up to 10 pending commands
                cur.execute("""
                    UPDATE worker_commands
                    SET status = 'delivered', delivered_at = NOW()
                    WHERE command_id IN (
                        SELECT command_id FROM worker_commands
                        WHERE (worker_id = %s OR worker_id IS NULL)
                          AND status = 'pending'
                          AND (expires_at IS NULL OR expires_at > NOW())
                        ORDER BY
                            CASE priority
                                WHEN 'critical' THEN 1
                                WHEN 'high'     THEN 2
                                WHEN 'normal'   THEN 3
                                ELSE 4
                            END,
                            created_at ASC
                        LIMIT 10
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING command_id, command_type, command_data, priority, target_filter
                """, (self.worker_id,))

                rows = cur.fetchall()

        if not rows:
            return

        for row in rows:
            command_id, command_type, command_data_str, priority, target_filter_str = row
            try:
                command_data = json.loads(command_data_str or '{}')
            except (ValueError, TypeError):
                command_data = {}

            # Filter broadcast commands by target_filter
            if target_filter_str:
                try:
                    target_filter = json.loads(target_filter_str)
                except (ValueError, TypeError):
                    target_filter = {}
                if not self._matches_filter(target_filter):
                    logger.debug(
                        f"Worker {self.worker_id} skipping broadcast command "
                        f"{command_id} (target_filter mismatch)"
                    )
                    continue

            # Execute in a daemon thread so the heartbeat loop never blocks
            t = threading.Thread(
                target=self._execute_command,
                args=(command_id, command_type, command_data),
                daemon=True,
            )
            t.start()

    def _matches_filter(self, target_filter: dict) -> bool:
        """Return True if this worker matches all keys in target_filter."""
        if not target_filter:
            return True
        if 'region' in target_filter and target_filter['region'] != self.region:
            return False
        if 'zone' in target_filter and target_filter['zone'] != self.zone:
            return False
        # Check arbitrary capability keys
        for key, value in target_filter.items():
            if key in ('region', 'zone'):
                continue
            if self.capabilities.get(key) != value:
                return False
        return True

    def _execute_command(self, command_id: str, command_type: str, command_data: dict):
        """Dispatch a single command to its handler."""
        logger.info(f"Worker {self.worker_id} executing command: {command_type} ({command_id})")
        self._report_command_result(command_id, 'executing')
        try:
            handlers = {
                'restart':         self._handle_restart,
                'pool_restart':    self._handle_pool_restart,
                'drain':           self._handle_drain,
                'update_code':     self._handle_update_code,
                'update_config':   self._handle_update_config,
                'pause_queue':     self._handle_pause_queue,
                'resume_queue':    self._handle_resume_queue,
                'set_concurrency': self._handle_set_concurrency,
                'check_health':    self._handle_check_health,
            }
            handler = handlers.get(command_type)
            if handler is None:
                raise ValueError(f"Unknown command type: {command_type}")
            result = handler(command_data)
            self._report_command_result(command_id, 'completed', result=result)
            logger.info(f"Worker {self.worker_id} completed command: {command_type} ({command_id})")
        except Exception as e:
            logger.error(f"Worker {self.worker_id} command {command_type} ({command_id}) failed: {e}")
            self._report_command_result(command_id, 'failed', error=str(e))

    # ──────────────────────────────────────────────────────────────────────────
    # Command Handlers
    # ──────────────────────────────────────────────────────────────────────────

    def _handle_restart(self, command_data: dict) -> dict:
        """Send SIGTERM after delay_seconds (default 5). In-flight tasks re-queue via broker."""
        delay = int(command_data.get('delay_seconds', 5))

        def _do_restart():
            time.sleep(delay)
            logger.info(f"Worker {self.worker_id}: sending SIGTERM for cold restart")
            os.kill(os.getpid(), signal.SIGTERM)

        threading.Thread(target=_do_restart, daemon=True).start()
        return {"action": "restart", "delay_seconds": delay, "scheduled": True}

    def _handle_pool_restart(self, command_data: dict) -> dict:
        """Hot-restart the Celery worker pool (reloads modules)."""
        if self.celery_app is None:
            raise RuntimeError("celery_app not injected; cannot pool_restart")
        self.celery_app.control.pool_restart(
            reload=True,
            destination=[self.hostname],
        )
        return {"action": "pool_restart", "destination": self.hostname}

    def _handle_drain(self, command_data: dict) -> dict:
        """Stop consuming, wait for in-flight tasks, then cold restart."""
        if self.celery_app is None:
            raise RuntimeError("celery_app not injected; cannot drain")
        queue = command_data.get('queue', 'default')
        wait_seconds = int(command_data.get('wait_seconds', 60))
        self.celery_app.control.cancel_consumer(queue, destination=[self.hostname])
        logger.info(
            f"Worker {self.worker_id}: draining queue '{queue}', "
            f"waiting {wait_seconds}s then restarting"
        )

        def _do_drain_restart():
            time.sleep(wait_seconds)
            logger.info(f"Worker {self.worker_id}: drain complete, sending SIGTERM")
            os.kill(os.getpid(), signal.SIGTERM)

        threading.Thread(target=_do_drain_restart, daemon=True).start()
        return {"action": "drain", "queue": queue, "wait_seconds": wait_seconds}

    def _handle_update_code(self, command_data: dict) -> dict:
        """Install a new package version then schedule a cold restart."""
        if 'wheel_url' in command_data:
            pip_cmd = ['pip', 'install', command_data['wheel_url'], '--quiet']
            version = command_data.get('version', 'unknown')
        elif 'package' in command_data and 'version' in command_data:
            pip_cmd = [
                'pip', 'install',
                f"{command_data['package']}=={command_data['version']}",
                '--quiet',
            ]
            if command_data.get('index_url'):
                pip_cmd += ['--index-url', command_data['index_url']]
            version = command_data['version']
        else:
            raise ValueError("update_code requires ('package'+'version') or 'wheel_url'")

        result = subprocess.run(pip_cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"pip install failed: {result.stderr[:500]}")

        self._update_sdk_version_in_db(version)

        # Schedule cold restart after 5s
        def _do_restart():
            time.sleep(5)
            logger.info(f"Worker {self.worker_id}: restarting after code update to {version}")
            os.kill(os.getpid(), signal.SIGTERM)

        threading.Thread(target=_do_restart, daemon=True).start()
        return {"action": "update_code", "version": version, "restart_scheduled": True}

    def _handle_update_config(self, command_data: dict) -> dict:
        """Update in-memory capabilities and persist to DB — no restart needed."""
        updates = command_data.get('capabilities', {})
        self.capabilities.update(updates)
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE worker_nodes
                        SET capabilities = %s, updated_at = NOW()
                        WHERE worker_id = %s
                    """, (json.dumps(self.capabilities), self.worker_id))
        except Exception as e:
            logger.error(f"Failed to persist updated capabilities: {e}")
        return {"action": "update_config", "capabilities": self.capabilities}

    def _handle_pause_queue(self, command_data: dict) -> dict:
        """Stop consuming from a queue."""
        if self.celery_app is None:
            raise RuntimeError("celery_app not injected; cannot pause_queue")
        queue = command_data.get('queue', 'default')
        self.celery_app.control.cancel_consumer(queue, destination=[self.hostname])
        return {"action": "pause_queue", "queue": queue}

    def _handle_resume_queue(self, command_data: dict) -> dict:
        """Resume consuming from a queue."""
        if self.celery_app is None:
            raise RuntimeError("celery_app not injected; cannot resume_queue")
        queue = command_data.get('queue', 'default')
        self.celery_app.control.add_consumer(queue, destination=[self.hostname])
        return {"action": "resume_queue", "queue": queue}

    def _handle_set_concurrency(self, command_data: dict) -> dict:
        """Grow or shrink the worker pool."""
        if self.celery_app is None:
            raise RuntimeError("celery_app not injected; cannot set_concurrency")
        direction = command_data.get('direction', 'grow')
        n = int(command_data.get('n', 1))
        if direction == 'grow':
            self.celery_app.control.pool_grow(n, destination=[self.hostname])
        else:
            self.celery_app.control.pool_shrink(n, destination=[self.hostname])
        return {"action": "set_concurrency", "direction": direction, "n": n}

    def _handle_check_health(self, command_data: dict) -> dict:
        """Collect platform info and Celery stats."""
        import platform
        info: dict = {
            "worker_id": self.worker_id,
            "hostname": self.hostname,
            "region": self.region,
            "zone": self.zone,
            "sdk_version": self.sdk_version,
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "pid": os.getpid(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if self.celery_app is not None:
            try:
                inspect = self.celery_app.control.inspect(
                    destination=[self.hostname], timeout=5
                )
                stats = inspect.stats()
                if stats:
                    info["celery_stats"] = stats.get(self.hostname, {})
            except Exception as e:
                info["celery_stats_error"] = str(e)
        return info

    # ──────────────────────────────────────────────────────────────────────────
    # DB Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _report_command_result(
        self,
        command_id: str,
        status: str,
        result: dict = None,
        error: str = None,
    ):
        """Update worker_commands with status, timestamps, result or error."""
        now = datetime.now(timezone.utc)
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    if status == 'executing':
                        cur.execute("""
                            UPDATE worker_commands
                            SET status = %s, executed_at = %s
                            WHERE command_id = %s
                        """, (status, now, command_id))
                    elif status == 'completed':
                        cur.execute("""
                            UPDATE worker_commands
                            SET status = %s, completed_at = %s, result = %s
                            WHERE command_id = %s
                        """, (status, now, json.dumps(result or {}), command_id))
                    elif status == 'failed':
                        cur.execute("""
                            UPDATE worker_commands
                            SET status = %s, completed_at = %s, error_message = %s
                            WHERE command_id = %s
                        """, (status, now, error, command_id))
        except Exception as e:
            logger.error(
                f"Failed to report command result for {command_id} (status={status}): {e}"
            )

    def _update_sdk_version_in_db(self, version: str):
        """Persist updated sdk_version to worker_nodes after a successful update_code."""
        self.sdk_version = version
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE worker_nodes
                        SET sdk_version = %s, updated_at = NOW()
                        WHERE worker_id = %s
                    """, (version, self.worker_id))
        except Exception as e:
            logger.error(f"Failed to update sdk_version in DB: {e}")
