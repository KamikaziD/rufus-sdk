from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict
import json
import asyncio
import logging
import time

import redis
from old.services.redis_service import redis_service

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    def __init__(self, redis_service_instance):
        self.active_connections: Dict[str, WebSocket] = {}
        self.redis_service = redis_service_instance
        self.pubsub = None
        self.pubsub_listener_task = None
        self.connection_lock = asyncio.Lock()

    async def startup(self):
        logger.debug("ConnectionManager startup method called.")
        if not self.pubsub:
            logger.debug(f"Redis service instance: {self.redis_service.redis}")
            self.pubsub = self.redis_service.redis.pubsub()
            
            # Initiate psubscribe (it doesn't return the channels immediately)
            await self.pubsub.psubscribe("agent_results:*", "agent_activity:*")
            
            # Explicitly wait for the psubscribe confirmation message from Redis
            while True:
                message = await self.pubsub.get_message(ignore_subscribe_messages=False, timeout=1.0)
                if message and message['type'] == 'psubscribe':
                    logger.debug(f"Pub/Sub psubscribe confirmed for channel: {message['channel']}")
                    break
                elif message:
                    logger.debug(f"Received unexpected message during psubscribe wait: {message}")
                
            try:
                self.pubsub_listener_task = asyncio.create_task(
                    self.run_pubsub_listener())
            except Exception as err:
                logger.error(
                    f"ConnectionManager startup error: {err}", exc_info=True)
            logger.debug(
                "ConnectionManager startup: Pub/Sub initialized and listener started.")

    async def shutdown(self):
        if self.pubsub_listener_task:
            logger.info("Cancelling Redis Pub/Sub listener task...")
            self.pubsub_listener_task.cancel()
            try:
                await self.pubsub_listener_task
            except asyncio.CancelledError:
                logger.info(
                    "Redis Pub/Sub listener task cancelled successfully.")
            except Exception as e:
                logger.error(
                    f"Error while cancelling Pub/Sub listener task: {e}", exc_info=True)
        if self.pubsub:
            await self.pubsub.punsubscribe("agent_results:*", "agent_activity:*")
            await self.pubsub.close()
            logger.info("Redis Pub/Sub unsubscribed and closed.")

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()

        superseded_connection = None
        async with self.connection_lock:
            superseded_connection = self.active_connections.pop(
                client_id, None)
            self.active_connections[client_id] = websocket
            total_connections = len(self.active_connections)

        if superseded_connection and superseded_connection is not websocket:
            logger.warning(
                "Superseding existing WebSocket connection for client %s. Active connections remain: %d",
                client_id, total_connections
            )
            try:
                await superseded_connection.close(code=4001, reason="Superseded by new connection")
            except RuntimeError as exc:
                logger.debug(
                    "Existing WebSocket for %s was already closed: %s", client_id, exc)

        logger.info("WebSocket connected: %s (active=%d)",
                    client_id, total_connections)
        await websocket.send_text("connected to the brain!")
        logger.info(f"Sent 'connected' message to {client_id}")

    async def disconnect(self, client_id: str, reason: str = "client disconnected"):
        async with self.connection_lock:
            removed = self.active_connections.pop(client_id, None)
            total_connections = len(self.active_connections)

        if removed:
            logger.info(
                "WebSocket disconnected: %s (active=%d, reason=%s)",
                client_id, total_connections, reason
            )
        else:
            logger.debug(
                "Disconnect for client %s ignored; no active connection found.", client_id)

    async def send_personal_message(self, message: str, client_id: str):
        websocket = self.active_connections.get(client_id)
        logger.debug(f"Attempting to send message to client {client_id}. WebSocket: {websocket}")
        if websocket:
            try:
                await websocket.send_text(message)
                logger.debug(f"Successfully sent message to client {client_id}")

                # Log delivery acknowledgement
                message_id = None
                try:
                    payload = json.loads(message)
                    if isinstance(payload, dict):
                        message_id = payload.get("message_id")
                except json.JSONDecodeError:
                    pass

                if message_id:
                    logger.info(
                        f"ACK: Successfully sent message with message_id {message_id} to client {client_id}")
                else:
                    logger.info(
                        f"ACK: Successfully sent message to client {client_id}")

            except (WebSocketDisconnect, RuntimeError) as e:
                logger.warning(
                    f"Failed to send message to client {client_id}: {e}. Disconnecting.")
                await self.disconnect(client_id, reason=f"send failed: {e}")
        else:
            logger.warning(
                f"Attempted to send message to disconnected client: {client_id}. No WebSocket found.")

    async def run_pubsub_listener(self):
        logger.debug("Redis Pub/Sub listener started.")
        if not self.pubsub:
            logger.error(
                "run_pubsub_listener called before pubsub was initialized.")
            return

        logger.info("Redis Pub/Sub listener started.")
        while True:
            try:
                message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    logger.debug(f"Message received by listener: {message}")
                    channel = message["channel"].decode("utf-8")
                    data = message["data"].decode("utf-8")

                    logger.debug(
                        f"Redis Pub/Sub message received on channel '{channel}'")

                    parts = channel.split(":")
                    if len(parts) == 2 and parts[0] in ("agent_results", "agent_activity"):
                        client_id = parts[1]
                        await self.send_personal_message(data, client_id)
                    else:
                        logger.warning(
                            f"Received message on unexpected channel format: {channel!r}")

                await asyncio.sleep(0.01)
            except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as e:
                logger.error(
                    f"Redis Pub/Sub connection error: {e}. Attempting to reconnect...", exc_info=True)
                await self._reconnect_pubsub()
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(
                    f"Error in Redis Pub/Sub listener: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _reconnect_pubsub(self):
        max_retries = 5
        base_delay = 1
        for i in range(max_retries):
            try:
                if self.pubsub:
                    await self.pubsub.close()
                self.pubsub = self.redis_service.redis.pubsub()
                await self.pubsub.psubscribe("agent_results:*", "agent_activity:*")
                logger.info(
                    f"Redis Pub/Sub reconnected successfully after {i+1} attempts.")
                return
            except redis.exceptions.ConnectionError as e:
                delay = base_delay * (2 ** i)
                logger.warning(
                    f"Redis reconnection attempt {i+1}/{max_retries} failed: {e}. Retrying in {delay}s.")
                await asyncio.sleep(delay)
        logger.critical(
            "Failed to re-establish Redis Pub/Sub connection. Listener will stop.")


manager = ConnectionManager(redis_service)


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"WS DATA | IN | : {data}")
            # Handle heartbeats
            is_ping = False
            payload = None
            if data == "ping":
                is_ping = True
            else:
                try:
                    payload = json.loads(data)
                    if isinstance(payload, dict) and payload.get("type") == "ping":
                        is_ping = True
                except json.JSONDecodeError:
                    pass  # Not a json message, so not a ping

            if is_ping:
                logger.debug("Received ping from %s, sending pong.", client_id)
                await websocket.send_text(json.dumps({"type": "pong", "ts": time.time()}))
                continue

            # For other messages, you might log them if needed, but for now we do nothing with them server-side
            logger.info("Received unhandled message from %s: %s",
                        client_id, data[:100])

    except WebSocketDisconnect:
        logger.info("Client %s disconnected gracefully.", client_id)
    except Exception as e:
        logger.error(
            f"Error in websocket endpoint for {client_id}: {e}", exc_info=True)
    finally:
        await manager.disconnect(client_id, reason="endpoint finished")
        logger.info("WebSocket endpoint finished for client %s.", client_id)