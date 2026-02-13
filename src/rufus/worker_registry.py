import os
import time
import threading
import json
import socket
import uuid
import logging
import psycopg2
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class WorkerRegistry:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.worker_id = os.getenv("WORKER_ID", f"worker-{uuid.uuid4().hex[:12]}")
        self.hostname = socket.gethostname()
        self.region = os.getenv("WORKER_REGION", "default")
        self.zone = os.getenv("WORKER_ZONE", "default")
        self.capabilities = json.loads(os.getenv("WORKER_CAPABILITIES", "{}"))
        self._stop_event = threading.Event()
        self._heartbeat_thread = None

    def _get_connection(self):
        return psycopg2.connect(self.db_url)

    def register(self):
        """Register the worker in the database."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO worker_nodes
                        (worker_id, hostname, region, zone, capabilities, status, last_heartbeat)
                        VALUES (%s, %s, %s, %s, %s, 'online', NOW())
                        ON CONFLICT (worker_id)
                        DO UPDATE SET
                            status = 'online',
                            last_heartbeat = NOW(),
                            updated_at = NOW();
                    """, (
                        self.worker_id,
                        self.hostname,
                        self.region,
                        self.zone,
                        json.dumps(self.capabilities)
                    ))
            logger.info(f"Worker {self.worker_id} registered successfully in region {self.region}.")
            self._start_heartbeat()
        except Exception as e:
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
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self):
        """Send heartbeats every 30 seconds."""
        logger.info(f"Worker {self.worker_id} heartbeat started.")
        while not self._stop_event.is_set():
            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE worker_nodes
                            SET last_heartbeat = NOW()
                            WHERE worker_id = %s
                        """, (self.worker_id,))
            except Exception as e:
                logger.error(f"Worker {self.worker_id} heartbeat failed: {e}")

            # Sleep for 30 seconds, checking stop event frequently
            for _ in range(30):
                if self._stop_event.is_set():
                    break
                time.sleep(1)
