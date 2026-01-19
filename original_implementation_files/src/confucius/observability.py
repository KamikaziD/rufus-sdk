import asyncio
import json
import logging
from typing import Dict, Set, Optional

from fastapi import WebSocket

from .persistence_postgres import get_postgres_store

logger = logging.getLogger(__name__)


class WorkflowMonitor:
    """
    Listens for PostgreSQL NOTIFY events on channel 'workflow_update' and
    forwards payloads to registered WebSocket clients.

    Usage:
        monitor = WorkflowMonitor()
        asyncio.create_task(monitor.start_listener())
    """

    def __init__(self):
        # execution_id -> set(WebSocket)
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self._running = False
        self._listen_task: Optional[asyncio.Task] = None

    async def start_listener(self):
        """
        Starts the background listener task on the postgres executor.
        """
        if self._running:
            logger.info("[MONITOR] Listener already running.")
            return

        self._running = True
        from .postgres_executor import pg_executor
        
        # This loop will run on the main FastAPI event loop.
        # It ensures the listener task on the executor is running.
        async def _monitor_loop():
            logger.info("[MONITOR] Starting PostgreSQL LISTEN/NOTIFY listener for 'workflow_update'")
            pg_executor.run_coroutine_future(self._executor_listener)
            while self._running:
                await asyncio.sleep(1)
            logger.info("[MONITOR] Listener stopped.")
            
        self._listen_task = asyncio.create_task(_monitor_loop())

    async def _executor_listener(self):
        """
        This coroutine runs on the PostgresExecutor's event loop.
        It maintains a dedicated connection to PostgreSQL to listen for notifications.
        """
        import asyncpg
        while self._running:
            try:
                store = await get_postgres_store()
                conn = await asyncpg.connect(dsn=store.db_url)
                
                # Have to use the main thread's loop
                main_loop = asyncio.get_running_loop()

                def _notification_callback(connection, pid, channel, payload):
                    # This is a synchronous callback from asyncpg.
                    # We need to schedule the async handler on the main event loop.
                    asyncio.run_coroutine_threadsafe(
                        self._handle_notification(connection, pid, channel, payload),
                        main_loop,
                    )

                await conn.add_listener("workflow_update", _notification_callback)
                logger.info("[MONITOR] Successfully listening on 'workflow_update' channel.")

                while self._running:
                    # Keep the connection alive
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"[MONITOR] Error in listener, will reconnect in 5s: {e}")
                await asyncio.sleep(5)
            finally:
                if 'conn' in locals() and not conn.is_closed():
                    try:
                        await conn.close()
                    except Exception as e:
                        logger.error(f"[MONITOR] Error closing connection: {e}")


    async def _handle_notification(self, connection, pid, channel, payload):
        """
        Callback invoked by asyncpg when a NOTIFY message arrives.
        payload is expected to be a JSON string containing at least 'execution_id' or 'id'.
        """
        try:
            data = json.loads(payload)
        except Exception:
            # If payload is plain text, wrap it
            logger.debug(f"[MONITOR] Received non-json payload: {payload}")
            data = {"payload": payload}

        # Compatibility: prefer 'execution_id' but accept 'id' too
        execution_id = data.get('execution_id') or data.get(
            'id') or data.get('workflow_id')

        if not execution_id:
            # Broadcast to all clients as fallback
            all_clients = []
            for clients in self.active_connections.values():
                all_clients.extend(list(clients))
            await self._broadcast_to_clients(all_clients, data)
            return

        clients = list(self.active_connections.get(execution_id, []))
        if not clients:
            logger.debug(
                f"[MONITOR] No active websocket clients for execution {execution_id}")
            return

        await self._broadcast_to_clients(clients, data)

    async def _broadcast_to_clients(self, clients: Set[WebSocket], data: dict):
        dead = []
        for ws in clients:
            try:
                await ws.send_json(data)
            except Exception as e:
                # Collect dead sockets for cleanup
                logger.debug(f"[MONITOR] WebSocket send failed: {e}")
                dead.append(ws)

        # Cleanup dead sockets from all registrations
        if dead:
            for execution_id, sockets in list(self.active_connections.items()):
                removed = False
                for ws in dead:
                    if ws in sockets:
                        sockets.discard(ws)
                        removed = True
                if removed and not sockets:
                    # remove empty set
                    del self.active_connections[execution_id]

    async def register_client(self, execution_id: str, websocket: WebSocket):
        """
        Register a WebSocket client for updates on a specific workflow execution.
        """
        if execution_id not in self.active_connections:
            self.active_connections[execution_id] = set()
        self.active_connections[execution_id].add(websocket)
        logger.debug(
            f"[MONITOR] Registered websocket for execution {execution_id}. Clients: {len(self.active_connections[execution_id])}")

    async def unregister_client(self, execution_id: str, websocket: WebSocket):
        """
        Unregister a WebSocket client.
        """
        if execution_id in self.active_connections:
            self.active_connections[execution_id].discard(websocket)
            if not self.active_connections[execution_id]:
                del self.active_connections[execution_id]
            logger.debug(
                f"[MONITOR] Unregistered websocket for execution {execution_id}")

    def stop(self):
        """
        Stop the background listener loop. Note: listener task must be cancelled externally
        if created with asyncio.create_task.
        """
        self._running = False


# Global singleton monitor that the FastAPI app can import and use.
monitor = WorkflowMonitor()
