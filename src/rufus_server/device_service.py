"""
Device management service for Rufus Edge Cloud Control Plane.

Handles:
- Device registration and authentication
- Config management with ETag caching
- Transaction sync (Store-and-Forward) with HMAC verification
- Device heartbeat and health monitoring
"""

import hashlib
import hmac as hmac_lib
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# DeviceService — Mixed: Some ops stay direct, some go through workflows
# ============================================================================
# Direct calls (no workflow overhead):
#   - register_device()            idempotent registration, no compensation needed
#   - update_heartbeat()           high-frequency, no rollback semantics
#   - get_device_status()          read-only
#   - get_active_config()          read-only
#   - get_device_commands()        read-only polling
#   - complete_command()           single-step idempotent ack
#
# Called FROM workflows (ConfigRollout uses these):
#   - create_config()              ConfigRollout.Create_Config_Version step
# ============================================================================

class DeviceService:
    """
    Service layer for device management operations.
    """

    def __init__(self, persistence, version_service=None, webhook_service=None):
        self.persistence = persistence
        self.version_service = version_service  # Optional for backward compat
        self.webhook_service = webhook_service  # Optional for webhook notifications

    # ─────────────────────────────────────────────────────────────────────────
    # Device Registration
    # ─────────────────────────────────────────────────────────────────────────

    async def register_device(
        self,
        device_id: str,
        device_type: str,
        device_name: str,
        merchant_id: str,
        firmware_version: str,
        sdk_version: str,
        location: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        public_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Register a new edge device.

        Returns:
            Dict with device_id, api_key, config_url, sync_url
        """
        import json

        # Generate API key
        api_key = f"rsk_{secrets.token_urlsafe(32)}"
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        # Check if device already exists
        existing = await self._get_device(device_id)
        if existing:
            raise ValueError(f"Device {device_id} already registered")

        # Insert device record (asyncpg uses $1, $2, etc. for placeholders)
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO edge_devices (
                    device_id, device_type, device_name, merchant_id,
                    location, api_key_hash, public_key, firmware_version,
                    sdk_version, capabilities, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'online')
                """,
                device_id, device_type, device_name, merchant_id,
                location, api_key_hash, public_key, firmware_version,
                sdk_version, json.dumps(capabilities or [])
            )

        logger.info(f"Registered device {device_id} for merchant {merchant_id}")

        # Dispatch webhook event
        if self.webhook_service:
            try:
                from rufus_server.webhook_service import WebhookEvent
                await self.webhook_service.dispatch_event(
                    WebhookEvent.DEVICE_REGISTERED,
                    {
                        "device_id": device_id,
                        "device_type": device_type,
                        "device_name": device_name,
                        "merchant_id": merchant_id,
                        "firmware_version": firmware_version,
                        "sdk_version": sdk_version,
                        "location": location
                    }
                )
            except Exception as e:
                logger.error(f"Failed to dispatch webhook for device registration: {e}")

        return {
            "device_id": device_id,
            "api_key": api_key,
            "config_url": f"/api/v1/devices/{device_id}/config",
            "sync_url": f"/api/v1/devices/{device_id}/sync",
            "heartbeat_interval": 60,
        }

    async def authenticate_device(self, device_id: str, api_key: str) -> bool:
        """Verify device API key."""
        device = await self._get_device(device_id)
        if not device:
            return False

        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return device.get("api_key_hash") == api_key_hash

    async def _get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get device by ID (internal, includes sensitive data)."""
        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM edge_devices WHERE device_id = $1",
                device_id
            )
            if row:
                return dict(row)
            return None

    async def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get device by ID (public, excludes sensitive data)."""
        device = await self._get_device(device_id)
        if device:
            # Remove sensitive fields
            device.pop('api_key_hash', None)
            device.pop('public_key', None)
        return device

    async def list_devices(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List all registered devices."""
        query = "SELECT * FROM edge_devices"
        params = []

        if status:
            query += " WHERE status = $1"
            params.append(status)

        query += f" ORDER BY registered_at DESC LIMIT {limit} OFFSET {offset}"

        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

            devices = []
            for row in rows:
                device = dict(row)
                # Remove sensitive fields
                device.pop('api_key_hash', None)
                device.pop('public_key', None)
                devices.append(device)

            return devices

    async def delete_device(self, device_id: str) -> None:
        """Delete a device from the registry."""
        device = await self._get_device(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM edge_devices WHERE device_id = $1",
                device_id
            )

        logger.info(f"Deleted device {device_id}")

    # ─────────────────────────────────────────────────────────────────────────
    # Config Management
    # ─────────────────────────────────────────────────────────────────────────

    async def get_active_config(self) -> Optional[Dict[str, Any]]:
        """Get the current active configuration."""
        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT config_id, config_version, config_data, etag, created_at
                FROM device_configs
                WHERE is_active = true
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            if row:
                return dict(row)
            return None

    async def create_config(
        self,
        config_version: str,
        config_data: Dict[str, Any],
        created_by: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new configuration version."""
        import json

        # Compute ETag
        config_json = json.dumps(config_data, sort_keys=True)
        etag = hashlib.sha256(config_json.encode()).hexdigest()

        async with self.persistence.pool.acquire() as conn:
            # Deactivate old configs
            await conn.execute(
                "UPDATE device_configs SET is_active = false WHERE is_active = true"
            )

            # Insert new config
            await conn.execute(
                """
                INSERT INTO device_configs (
                    config_version, config_data, etag, is_active, created_by, description
                ) VALUES ($1, $2, $3, true, $4, $5)
                """,
                config_version, config_json, etag, created_by, description
            )

        logger.info(f"Created config version {config_version}")

        return {
            "config_version": config_version,
            "etag": etag,
            "is_active": True,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Transaction Sync (SAF)
    # ─────────────────────────────────────────────────────────────────────────

    def _verify_hmac(self, api_key: str, data: str, expected_hmac: str) -> bool:
        """
        Verify HMAC signature for transaction payload.

        Args:
            api_key: Device API key (secret)
            data: String data that was signed
            expected_hmac: HMAC signature from device

        Returns:
            True if HMAC is valid, False otherwise
        """
        try:
            computed_hmac = hmac_lib.new(
                api_key.encode('utf-8'),
                data.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            # Use constant-time comparison to prevent timing attacks
            return hmac_lib.compare_digest(computed_hmac, expected_hmac)
        except Exception as e:
            logger.error(f"HMAC verification error: {e}")
            return False

    async def sync_transactions(
        self,
        device_id: str,
        transactions: List[Dict[str, Any]],
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process synced transactions from edge device with HMAC verification.

        Args:
            device_id: Device identifier
            transactions: List of transaction dicts with HMAC signatures
            api_key: Device API key for HMAC verification (required)

        Returns:
            Dict with accepted, rejected lists
        """
        accepted = []
        rejected = []

        # Get device to verify API key (if not provided)
        if not api_key:
            device = await self._get_device(device_id)
            if not device:
                return {
                    "accepted": [],
                    "rejected": [{"transaction_id": "unknown", "reason": "Device not found"}],
                    "server_sequence": 0,
                }
            # We don't have the raw API key, only the hash - HMAC verification requires raw key
            # This means api_key MUST be provided by the endpoint handler
            logger.error(f"API key not provided for HMAC verification (device {device_id})")
            return {
                "accepted": [],
                "rejected": [{"transaction_id": "unknown", "reason": "HMAC verification not possible"}],
                "server_sequence": 0,
            }

        async with self.persistence.pool.acquire() as conn:
            for txn in transactions:
                # Verify HMAC if present
                if "hmac" in txn and txn["hmac"]:
                    # Reconstruct the signed data (must match edge device format)
                    hmac_input = (
                        f"{txn.get('transaction_id', '')}|"
                        f"{txn.get('encrypted_blob', '')}|"
                        f"{txn.get('encryption_key_id', 'default')}"
                    )

                    if not self._verify_hmac(api_key, hmac_input, txn["hmac"]):
                        logger.warning(
                            f"HMAC verification failed for transaction {txn.get('transaction_id')} "
                            f"from device {device_id}"
                        )
                        rejected.append({
                            "transaction_id": txn.get("transaction_id"),
                            "status": "REJECTED",
                            "reason": "HMAC verification failed",
                        })
                        continue
                else:
                    # HMAC required but not present
                    logger.warning(
                        f"Transaction {txn.get('transaction_id')} missing HMAC signature"
                    )
                    rejected.append({
                        "transaction_id": txn.get("transaction_id"),
                        "status": "REJECTED",
                        "reason": "HMAC signature required",
                    })
                    continue
                try:
                    # Check idempotency (use existing connection)
                    existing = await self._get_transaction_by_idempotency(
                        txn.get("idempotency_key"),
                        conn=conn
                    )
                    if existing:
                        accepted.append({
                            "transaction_id": txn["transaction_id"],
                            "status": "DUPLICATE",
                            "server_id": existing["transaction_id"],
                        })
                        continue

                    # Insert transaction (idempotent - ignore duplicates from race conditions)
                    result = await conn.fetchrow(
                        """
                        INSERT INTO saf_transactions (
                            transaction_id, idempotency_key, device_id, merchant_id,
                            amount_cents, currency, card_token, card_last_four,
                            encrypted_payload, encryption_key_id, status, synced_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'synced', $11)
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING transaction_id
                        """,
                        txn["transaction_id"],
                        txn["idempotency_key"],
                        device_id,
                        txn.get("merchant_id", ""),
                        txn.get("amount_cents", 0),
                        txn.get("currency", "USD"),
                        txn.get("card_token", ""),
                        txn.get("card_last_four", ""),
                        txn.get("encrypted_payload"),
                        txn.get("encryption_key_id"),
                        datetime.utcnow()
                    )

                    # Check if row was actually inserted (result is None if conflict occurred)
                    if result:
                        accepted.append({
                            "transaction_id": txn["transaction_id"],
                            "status": "ACCEPTED",
                            "server_id": txn["transaction_id"],
                        })
                    else:
                        # Race condition - transaction was inserted by another request
                        accepted.append({
                            "transaction_id": txn["transaction_id"],
                            "status": "DUPLICATE",
                            "server_id": txn["transaction_id"],
                        })

                except Exception as e:
                    logger.error(f"Failed to sync transaction {txn.get('transaction_id')}: {e}")
                    rejected.append({
                        "transaction_id": txn.get("transaction_id"),
                        "status": "REJECTED",
                        "reason": str(e),
                    })

            # Update device last_sync_at
            await conn.execute(
                "UPDATE edge_devices SET last_sync_at = $1 WHERE device_id = $2",
                datetime.utcnow(), device_id  # Pass datetime object, not string
            )

        return {
            "accepted": accepted,
            "rejected": rejected,
            "server_sequence": 0,  # TODO: Implement sequencing
        }

    async def _get_transaction_by_idempotency(
        self,
        key: str,
        conn=None
    ) -> Optional[Dict[str, Any]]:
        """
        Get transaction by idempotency key.

        Args:
            key: Idempotency key to look up
            conn: Optional existing connection to reuse (avoids nested acquisition)
        """
        if not key:
            return None

        # If connection provided, use it; otherwise acquire new one
        if conn:
            row = await conn.fetchrow(
                "SELECT * FROM saf_transactions WHERE idempotency_key = $1",
                key
            )
            if row:
                return dict(row)
            return None
        else:
            async with self.persistence.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM saf_transactions WHERE idempotency_key = $1",
                    key
                )
                if row:
                    return dict(row)
                return None

    # ─────────────────────────────────────────────────────────────────────────
    # Heartbeat & Health
    # ─────────────────────────────────────────────────────────────────────────

    async def process_heartbeat(
        self,
        device_id: str,
        status: str,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process device heartbeat.

        Returns:
            Dict with ack and pending commands
        """
        import json

        async with self.persistence.pool.acquire() as conn:
            # Update device heartbeat
            await conn.execute(
                """
                UPDATE edge_devices
                SET last_heartbeat_at = $1, status = $2, metadata = $3
                WHERE device_id = $4
                """,
                datetime.utcnow(),  # Pass datetime object, not string
                status,
                json.dumps(metrics or {}),
                device_id
            )

        # Get pending commands
        commands = await self._get_pending_commands(device_id)

        return {
            "ack": True,
            "commands": commands,
        }

    async def _get_pending_commands(self, device_id: str) -> List[Dict[str, Any]]:
        """Get pending commands for device."""
        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT command_id, command_type, command_data
                FROM device_commands
                WHERE device_id = $1 AND status = 'pending'
                ORDER BY created_at ASC
                LIMIT 10
                """,
                device_id
            )
            commands = []
            for row in rows:
                commands.append({
                    "command_id": row["command_id"],
                    "command_type": row["command_type"],
                    "command_data": row["command_data"],
                })

                # Mark as sent
                await conn.execute(
                    "UPDATE device_commands SET status = 'sent', sent_at = $1 WHERE command_id = $2",
                    datetime.utcnow(), row["command_id"]
                )

            return commands

    async def send_command(
        self,
        device_id: str,
        command_type: str,
        command_data: Optional[Dict[str, Any]] = None,
        command_version: Optional[str] = None,
        expires_in_seconds: int = 3600,
        retry_policy: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Queue a command for a device.

        Args:
            device_id: Target device ID
            command_type: Type of command to execute
            command_data: Command parameters
            command_version: Command schema version (optional, defaults to latest)
            expires_in_seconds: Time until command expires
            retry_policy: Optional retry configuration
                Example: {
                    "max_retries": 3,
                    "initial_delay_seconds": 10,
                    "backoff_strategy": "exponential"
                }

        Returns:
            command_id: Unique command identifier
        """
        import uuid
        import json

        # Get version (explicit or latest)
        if self.version_service:
            if not command_version:
                latest = await self.version_service.get_latest_version(command_type)
                command_version = latest.version if latest else "1.0.0"

            # Validate command data against schema
            validation = await self.version_service.validate_command_data(
                command_type, command_version, command_data or {}
            )
            if not validation.valid:
                raise ValueError(f"Invalid command data: {', '.join(validation.errors)}")

            # Log warnings (e.g., deprecated version)
            for warning in validation.warnings:
                logger.warning(f"Command validation warning: {warning}")

        command_id = str(uuid.uuid4())
        expires_at = (datetime.utcnow() + timedelta(seconds=expires_in_seconds))

        # Extract max_retries for quick filtering
        max_retries = retry_policy.get("max_retries", 0) if retry_policy else 0

        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO device_commands (
                    command_id, device_id, command_type, command_data,
                    command_version, expires_at, retry_policy, max_retries
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                command_id,
                device_id,
                command_type,
                json.dumps(command_data or {}),
                command_version,
                expires_at,
                json.dumps(retry_policy) if retry_policy else None,
                max_retries
            )

        retry_info = f" (with {max_retries} retries)" if max_retries > 0 else ""
        version_info = f"@{command_version}" if command_version else ""
        logger.info(f"Queued command {command_type}{version_info} for device {device_id}{retry_info}")

        # Dispatch webhook event
        if self.webhook_service:
            try:
                from rufus_server.webhook_service import WebhookEvent
                await self.webhook_service.dispatch_event(
                    WebhookEvent.COMMAND_CREATED,
                    {
                        "command_id": command_id,
                        "device_id": device_id,
                        "command_type": command_type,
                        "command_version": command_version,
                        "expires_at": expires_at.isoformat(),
                        "max_retries": max_retries
                    }
                )
            except Exception as e:
                logger.error(f"Failed to dispatch webhook for command creation: {e}")

        return command_id

    async def list_commands(
        self,
        device_id: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List commands for a device, optionally filtered by status."""
        import json

        async with self.persistence.pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT command_id, command_type, command_data, status,
                           created_at, sent_at, completed_at, error_message
                    FROM device_commands
                    WHERE device_id = $1 AND status = $2
                    ORDER BY created_at DESC
                    """,
                    device_id,
                    status
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT command_id, command_type, command_data, status,
                           created_at, sent_at, completed_at, error_message
                    FROM device_commands
                    WHERE device_id = $1
                    ORDER BY created_at DESC
                    """,
                    device_id
                )

            commands = []
            for row in rows:
                commands.append({
                    "command_id": row["command_id"],
                    "command_type": row["command_type"],
                    "command_data": row["command_data"],
                    "status": row["status"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "sent_at": row["sent_at"].isoformat() if row["sent_at"] else None,
                    "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                    "error": row["error_message"],
                })

            return commands

    async def get_command_status(
        self,
        device_id: str,
        command_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get status of a specific command."""
        import json

        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT command_id, device_id, command_type, command_data, status,
                       created_at, sent_at, completed_at, error_message
                FROM device_commands
                WHERE device_id = $1 AND command_id = $2
                """,
                device_id,
                command_id
            )

            if not row:
                return None

            return {
                "command_id": row["command_id"],
                "device_id": row["device_id"],
                "command_type": row["command_type"],
                "command_data": row["command_data"],
                "status": row["status"],
                "result": json.loads(row["command_data"]) if row["command_data"] else {},
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "delivered_at": row["sent_at"].isoformat() if row["sent_at"] else None,
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                "error": row["error_message"],
            }

    async def update_command_status(
        self,
        device_id: str,
        command_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> bool:
        """
        Update command status (called by device when reporting back).

        Handles automatic retry scheduling for failed commands.
        """
        import json
        from .retry_policy import RetryPolicy

        async with self.persistence.pool.acquire() as conn:
            # First, get current command state
            cmd = await conn.fetchrow(
                """
                SELECT retry_policy, retry_count, max_retries
                FROM device_commands
                WHERE device_id = $1 AND command_id = $2
                """,
                device_id,
                command_id
            )

            if not cmd:
                return False

            # Build update query
            updates = ["status = $3"]
            params = [device_id, command_id, status]
            param_count = 3

            # Handle completed commands
            if status == "completed":
                param_count += 1
                updates.append(f"completed_at = ${param_count}")
                params.append(datetime.utcnow())

                # Clear retry fields on success
                updates.append("next_retry_at = NULL")

            # Handle failed commands with retry policy
            elif status == "failed" and cmd["retry_policy"]:
                retry_policy_dict = json.loads(cmd["retry_policy"])
                retry_policy = RetryPolicy.from_dict(retry_policy_dict)
                retry_count = cmd["retry_count"]

                if retry_policy.should_retry(retry_count):
                    # Schedule retry
                    next_retry = retry_policy.calculate_next_retry(retry_count)

                    param_count += 1
                    updates.append(f"retry_count = ${param_count}")
                    params.append(retry_count + 1)

                    param_count += 1
                    updates.append(f"next_retry_at = ${param_count}")
                    params.append(next_retry)

                    param_count += 1
                    updates.append(f"last_retry_at = ${param_count}")
                    params.append(datetime.utcnow())

                    logger.info(
                        f"Command {command_id} failed, scheduling retry {retry_count + 1}/{retry_policy.max_retries} "
                        f"at {next_retry.isoformat()}"
                    )
                else:
                    # No more retries
                    logger.warning(
                        f"Command {command_id} failed permanently after {retry_count} retries"
                    )

            # Store result if provided
            if result:
                param_count += 1
                updates.append(f"command_data = ${param_count}")
                params.append(json.dumps(result))

            # Store error message
            if error:
                param_count += 1
                updates.append(f"error_message = ${param_count}")
                params.append(error)

            # Execute update
            query = f"""
                UPDATE device_commands
                SET {', '.join(updates)}
                WHERE device_id = $1 AND command_id = $2
            """

            result = await conn.execute(query, *params)
            return result != "UPDATE 0"

    async def process_retries(self) -> Dict[str, int]:
        """
        Process commands pending retry.

        Called by background worker to re-queue failed commands.

        Returns:
            Dict with retry statistics
        """
        async with self.persistence.pool.acquire() as conn:
            # Find commands ready for retry
            rows = await conn.fetch(
                """
                SELECT command_id, device_id, command_type, retry_count
                FROM device_commands
                WHERE status = 'failed'
                  AND next_retry_at IS NOT NULL
                  AND next_retry_at <= $1
                  AND retry_count < max_retries
                ORDER BY next_retry_at ASC
                LIMIT 100
                """,
                datetime.utcnow()
            )

            retried_count = 0
            for row in rows:
                # Reset command to pending for retry
                result = await conn.execute(
                    """
                    UPDATE device_commands
                    SET status = 'pending',
                        next_retry_at = NULL,
                        sent_at = NULL,
                        error_message = NULL
                    WHERE command_id = $1
                    """,
                    row["command_id"]
                )

                if result != "UPDATE 0":
                    retried_count += 1
                    logger.info(
                        f"Retrying command {row['command_type']} for device {row['device_id']} "
                        f"(attempt {row['retry_count'] + 1})"
                    )

            return {
                "retries_processed": retried_count,
                "timestamp": datetime.utcnow().isoformat()
            }
