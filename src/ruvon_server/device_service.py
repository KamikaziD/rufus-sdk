"""
Device management service for Ruvon Edge Cloud Control Plane.

Handles:
- Device registration and authentication
- Config management with ETag caching
- Transaction sync (Store-and-Forward) with HMAC verification
- Device heartbeat and health monitoring
"""

import hashlib
import hmac as hmac_lib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
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
        import uuid as _uuid
        device_row_id = str(_uuid.uuid4())

        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO edge_devices (
                    id, device_id, device_type, device_name, merchant_id,
                    location, api_key_hash, public_key, firmware_version,
                    sdk_version, capabilities, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'online')
                """,
                device_row_id, device_id, device_type, device_name, merchant_id,
                location, api_key_hash, public_key, firmware_version,
                sdk_version, json.dumps(capabilities or [])
            )

        logger.info(f"Registered device {device_id} for merchant {merchant_id}")

        # Auto-create per-device config seeded by device_type
        await self._create_device_config(device_id, device_type)

        # Dispatch webhook event
        if self.webhook_service:
            try:
                from ruvon_server.webhook_service import WebhookEvent
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

    async def get_active_config(self, device_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get the current active configuration.

        If device_id is provided, returns per-device config first, then falls back to
        the global fleet config (where device_id IS NULL).
        """
        async with self.persistence.pool.acquire() as conn:
            # Try device-specific config first
            if device_id:
                row = await conn.fetchrow(
                    """
                    SELECT config_id, config_version, config_data, etag, created_at
                    FROM device_configs
                    WHERE is_active = true AND device_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    device_id
                )
                if row:
                    return dict(row)

            # Fall back to global fleet config
            row = await conn.fetchrow(
                """
                SELECT config_id, config_version, config_data, etag, created_at
                FROM device_configs
                WHERE is_active = true AND device_id IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            if row:
                return dict(row)
            return None

    async def save_device_config(
        self,
        device_id: str,
        config_data: Dict[str, Any],
        config_version: Optional[str] = None,
        description: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save per-device configuration (creates or replaces the active device config)."""
        import json

        config_json = json.dumps(config_data, sort_keys=True)
        etag = hashlib.sha256(config_json.encode()).hexdigest()

        if not config_version:
            config_version = f"device-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        import uuid as _uuid
        row_id = str(_uuid.uuid4())
        async with self.persistence.pool.acquire() as conn:
            # Deactivate previous per-device configs for this device only
            await conn.execute(
                "UPDATE device_configs SET is_active = false WHERE is_active = true AND device_id = $1",
                device_id
            )
            # Insert new per-device config
            await conn.execute(
                """
                INSERT INTO device_configs (
                    id, device_id, config_version, config_data, etag, is_active, created_by, description
                ) VALUES ($1, $2, $3, $4, $5, true, $6, $7)
                """,
                row_id, device_id, config_version, config_json, etag, created_by or "admin", description
            )

        logger.info(f"Saved per-device config {config_version} for device {device_id}")
        return {
            "config_version": config_version,
            "etag": etag,
            "is_active": True,
            "device_id": device_id,
        }

    async def _create_device_config(self, device_id: str, device_type: str) -> None:
        """Auto-create a default config for a newly registered device (seeded by device_type)."""
        import json

        if device_type == "atm":
            config_data = {
                "floor_limit": 500.0,
                "max_offline_transactions": 50,
                "offline_timeout_hours": 12,
                "supported_card_types": ["visa", "mastercard"],
                "require_pin_above": 0.0,
                "require_signature_above": 0.0,
                "fraud_rules": [],
                "features": {
                    "offline_mode": True,
                    "contactless": False,
                    "chip_fallback": True,
                    "manual_entry": False,
                },
                "workflows": {},
                "sync_interval_seconds": 30,
                "heartbeat_interval_seconds": 45,
            }
        else:  # pos and everything else
            config_data = {
                "floor_limit": 1000.0,
                "max_offline_transactions": 100,
                "offline_timeout_hours": 24,
                "supported_card_types": ["visa", "mastercard", "amex", "discover"],
                "require_pin_above": 50.0,
                "require_signature_above": 25.0,
                "fraud_rules": [],
                "features": {
                    "offline_mode": True,
                    "contactless": True,
                    "chip_fallback": True,
                    "manual_entry": False,
                },
                "workflows": {},
                "sync_interval_seconds": 30,
                "heartbeat_interval_seconds": 60,
            }

        config_json = json.dumps(config_data, sort_keys=True)
        etag = hashlib.sha256(config_json.encode()).hexdigest()
        config_version = f"device-default-{device_type}"

        try:
            import uuid as _uuid
            row_id = str(_uuid.uuid4())
            async with self.persistence.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO device_configs (
                        id, device_id, config_version, config_data, etag, is_active, created_by, description
                    ) VALUES ($1, $2, $3, $4, $5, true, 'system', $6)
                    """,
                    row_id, device_id, config_version, config_json, etag,
                    f"Auto-created default {device_type} config on registration"
                )
            logger.info(f"Created default {device_type} config for device {device_id}")
        except Exception as e:
            logger.warning(f"Failed to create default config for device {device_id}: {e}")

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
        device_sequence: int = 0,
        payload_signature: Optional[str] = None,
        relay_metadata: Optional[Dict[str, Any]] = None,
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

        # Ed25519 payload verification (only when a signature header is present)
        if payload_signature:
            device_record = await self._get_device(device_id)
            public_key_b64 = device_record.get("public_key") if device_record else None

            if public_key_b64:
                try:
                    import base64 as _b64
                    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                    pub_key_bytes = _b64.b64decode(public_key_b64)
                    public_key = Ed25519PublicKey.from_public_bytes(pub_key_bytes)
                    sig_bytes = _b64.b64decode(payload_signature)
                    payload_bytes = json.dumps(transactions, sort_keys=True).encode()
                    public_key.verify(sig_bytes, payload_bytes)
                except Exception as e:
                    logger.warning(f"Ed25519 signature verification failed for device {device_id}: {e}")
                    return {
                        "accepted": [],
                        "rejected": [{"transaction_id": "unknown", "reason": "Ed25519 signature verification failed"}],
                        "server_sequence": device_sequence,
                    }

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

        # Phase 1: HMAC verification — CPU only, no DB round-trips
        valid_txns = []
        for txn in transactions:
            if "hmac" in txn and txn["hmac"]:
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
                else:
                    valid_txns.append(txn)
            else:
                logger.warning(
                    f"Transaction {txn.get('transaction_id')} missing HMAC signature"
                )
                rejected.append({
                    "transaction_id": txn.get("transaction_id"),
                    "status": "REJECTED",
                    "reason": "HMAC signature required",
                })

        # Relay metadata applies to all transactions in the batch
        relay_device_id = relay_metadata.get("relay_device_id") if relay_metadata else None
        relay_source_device_id = relay_metadata.get("relay_source_device_id") if relay_metadata else None
        hop_count = relay_metadata.get("hop_count") if relay_metadata else None
        relayed_at_raw = relay_metadata.get("relayed_at") if relay_metadata else None
        relayed_at = None
        if relayed_at_raw:
            try:
                relayed_at = datetime.fromisoformat(str(relayed_at_raw).replace("Z", "+00:00"))
            except Exception:
                relayed_at = None

        async with self.persistence.pool.acquire() as conn:
            # Phase 2: single UNNEST INSERT for all HMAC-verified transactions.
            # ON CONFLICT (idempotency_key) DO NOTHING silently skips duplicates;
            # RETURNING tells us which rows were actually inserted vs already present.
            # This replaces N×(SELECT+INSERT) round-trips with 1 round-trip.
            if valid_txns:
                try:
                    rows = await conn.fetch(
                        """
                        INSERT INTO saf_transactions (
                            id, transaction_id, idempotency_key, device_id, merchant_id,
                            amount_cents, currency, card_token, card_last_four,
                            encrypted_payload, encryption_key_id, workflow_id,
                            relay_device_id, relay_source_device_id, hop_count, relayed_at,
                            status, synced_at
                        )
                        SELECT
                            t.row_id,
                            t.transaction_id, t.idempotency_key,
                            $1,
                            t.merchant_id, t.amount_cents, t.currency,
                            t.card_token, t.card_last_four,
                            t.encrypted_payload, t.encryption_key_id, t.workflow_id,
                            $2, $3, $4, $5,
                            'synced', NOW()
                        FROM UNNEST(
                            $6::uuid[], $7::text[], $8::text[], $9::text[], $10::int[],
                            $11::text[], $12::text[], $13::text[],
                            $14::text[], $15::text[], $16::text[]
                        ) AS t(
                            row_id, transaction_id, idempotency_key, merchant_id, amount_cents,
                            currency, card_token, card_last_four,
                            encrypted_payload, encryption_key_id, workflow_id
                        )
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING transaction_id
                        """,
                        device_id,
                        relay_device_id, relay_source_device_id, hop_count, relayed_at,
                        [uuid.uuid4() for _ in valid_txns],
                        [t["transaction_id"] for t in valid_txns],
                        [t.get("idempotency_key", t["transaction_id"]) for t in valid_txns],
                        [t.get("merchant_id", "") for t in valid_txns],
                        [t.get("amount_cents", 0) for t in valid_txns],
                        [t.get("currency", "USD") for t in valid_txns],
                        [t.get("card_token", "") for t in valid_txns],
                        [t.get("card_last_four", "") for t in valid_txns],
                        [t.get("encrypted_payload") for t in valid_txns],
                        [t.get("encryption_key_id") for t in valid_txns],
                        [t.get("workflow_id") for t in valid_txns],
                    )
                    inserted_ids = {r["transaction_id"] for r in rows}
                    for txn in valid_txns:
                        tid = txn["transaction_id"]
                        if tid in inserted_ids:
                            accepted.append({"transaction_id": tid, "status": "ACCEPTED", "server_id": tid})
                        else:
                            accepted.append({"transaction_id": tid, "status": "DUPLICATE", "server_id": tid})
                except Exception as e:
                    logger.error(f"Batch INSERT failed for device {device_id}: {e}")
                    for txn in valid_txns:
                        rejected.append({
                            "transaction_id": txn.get("transaction_id"),
                            "status": "REJECTED",
                            "reason": str(e),
                        })

            await conn.execute(
                "UPDATE edge_devices SET last_sync_at = $1 WHERE device_id = $2",
                datetime.utcnow(), device_id,
            )

        return {
            "accepted": accepted,
            "rejected": rejected,
            "server_sequence": device_sequence,
        }

    async def list_saf_transactions(self, device_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """List synced SAF transactions for a device."""
        async with self.persistence.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT transaction_id, merchant_id, amount_cents, currency,
                          card_last_four, status, workflow_id, synced_at, created_at,
                          relay_device_id, relay_source_device_id, hop_count, relayed_at
                   FROM saf_transactions WHERE device_id = $1
                   ORDER BY synced_at DESC NULLS LAST LIMIT $2""",
                device_id, limit,
            )
            result = []
            for r in rows:
                d = dict(r)
                # Convert cents to float for display
                d["amount"] = d["amount_cents"] / 100 if d.get("amount_cents") is not None else None
                result.append(d)
            return result

    async def update_device(self, device_id: str, updates: dict) -> bool:
        """Update allowed device fields."""
        allowed = {"sdk_version", "firmware_version", "device_name", "location"}
        fields = {k: v for k, v in updates.items() if k in allowed and v is not None}
        if not fields:
            return False
        set_clause = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(fields))
        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE edge_devices SET {set_clause} WHERE device_id = $1",
                device_id, *fields.values(),
            )
        return result != "UPDATE 0"

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
        vector_advisory: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process device heartbeat.

        vector_advisory: RUVON advisory state dict with keys:
          relay_score, connectivity_quality, known_peers, is_local_master.
          Stored in edge_devices.mesh_advisory (JSON) for topology queries.

        Returns:
            Dict with ack and pending commands
        """
        import json

        async with self.persistence.pool.acquire() as conn:
            # Update device heartbeat (include mesh_advisory when present)
            # Use naive UTC: asyncpg requires naive datetime for TIMESTAMP WITHOUT TIME ZONE columns
            _now = datetime.now(timezone.utc).replace(tzinfo=None)
            if vector_advisory is not None:
                await conn.execute(
                    """
                    UPDATE edge_devices
                    SET last_heartbeat_at = $1, status = $2, metadata = $3,
                        mesh_advisory = $4
                    WHERE device_id = $5
                    """,
                    _now,
                    status,
                    json.dumps(metrics or {}),
                    json.dumps(vector_advisory),
                    device_id,
                )
            else:
                await conn.execute(
                    """
                    UPDATE edge_devices
                    SET last_heartbeat_at = $1, status = $2, metadata = $3
                    WHERE device_id = $4
                    """,
                    _now,
                    status,
                    json.dumps(metrics or {}),
                    device_id,
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
            command_ids = []
            for row in rows:
                raw_data = row["command_data"]
                if isinstance(raw_data, str):
                    try:
                        raw_data = json.loads(raw_data)
                    except (json.JSONDecodeError, ValueError):
                        raw_data = {}
                commands.append({
                    "command_id": row["command_id"],
                    "command_type": row["command_type"],
                    "command_data": raw_data,
                })
                command_ids.append(row["command_id"])

            # Batch mark all fetched commands as sent — 1 round-trip regardless of count
            if command_ids:
                await conn.execute(
                    "UPDATE device_commands SET status = 'sent', sent_at = $1 WHERE command_id = ANY($2::text[])",
                    datetime.utcnow(), command_ids
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
                command_version = latest.version if latest else None

            # Only validate if a schema is registered for this command type
            if command_version:
                validation = await self.version_service.validate_command_data(
                    command_type, command_version, command_data or {}
                )
                if not validation.valid:
                    raise ValueError(f"Invalid command data: {', '.join(validation.errors)}")

                # Log warnings (e.g., deprecated version)
                for warning in validation.warnings:
                    logger.warning(f"Command validation warning: {warning}")

        command_id = str(uuid.uuid4())
        row_id = str(uuid.uuid4())
        expires_at = (datetime.utcnow() + timedelta(seconds=expires_in_seconds))

        # Extract max_retries for quick filtering
        max_retries = retry_policy.get("max_retries", 0) if retry_policy else 0

        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO device_commands (
                    id, command_id, device_id, command_type, command_data,
                    command_version, expires_at, retry_policy, max_retries
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                row_id,
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
                from ruvon_server.webhook_service import WebhookEvent
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

    # ─────────────────────────────────────────────────────────────────────────
    # API Key Rotation
    # ─────────────────────────────────────────────────────────────────────────

    async def rotate_api_key(
        self,
        device_id: str,
        current_api_key: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Rotate the API key for a device.

        Requires the current API key for possession proof. The new key is
        returned in plaintext only once — the caller must store it immediately.

        Returns the new key on success, None if the current key is invalid.
        """
        # Verify current key
        is_valid = await self.authenticate_device(device_id, current_api_key)
        if not is_valid:
            logger.warning(f"rotate_api_key: invalid current key for device {device_id}")
            return None

        new_key = secrets.token_urlsafe(32)
        new_key_hash = hashlib.sha256(new_key.encode()).hexdigest()
        now = datetime.utcnow()

        async with self.persistence.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE edge_devices
                SET api_key_hash = $1,
                    api_key_rotated_at = $2,
                    updated_at = $2
                WHERE device_id = $3
                """,
                new_key_hash, now, device_id,
            )

        if result == "UPDATE 0":
            logger.error(f"rotate_api_key: device {device_id} not found during UPDATE")
            return None

        logger.info(f"API key rotated for device {device_id}")
        return {
            "device_id": device_id,
            "new_api_key": new_key,  # Only time returned in plaintext
            "rotated_at": now.isoformat(),
        }

    async def register_relay_server(self, device_id: str, host: str, port: int) -> dict:
        """
        Record that this device is running a RUVON peer relay server.
        Sets relay_server_url so /mesh-peers can discover it.
        """
        relay_url = f"http://{host}:{port}"
        db = self.persistence
        if not hasattr(db, 'pool'):
            return {"device_id": device_id, "relay_server_url": relay_url}
        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE edge_devices SET relay_server_url = $1 WHERE device_id = $2",
                relay_url, device_id,
            )
        logger.info(f"[RUVON] Relay server registered for {device_id}: {relay_url}")
        return {"device_id": device_id, "relay_server_url": relay_url}

    async def get_mesh_peers(self, device_id: str, max_age_seconds: int = 300) -> list:
        """
        Return active devices (excluding self) that are advertising a relay server URL.
        Active = last_heartbeat_at within max_age_seconds (default 5 min).
        Result is sorted by last_heartbeat_at DESC so freshest peers come first.
        """
        db = self.persistence
        if not hasattr(db, 'pool'):
            return []
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT device_id, relay_server_url, last_heartbeat_at
                    FROM edge_devices
                    WHERE relay_server_url IS NOT NULL
                      AND device_id != $1
                      AND last_heartbeat_at > NOW() - ($2 * INTERVAL '1 second')
                    ORDER BY last_heartbeat_at DESC
                    """,
                    device_id,
                    max_age_seconds,
                )
            return [
                {
                    "device_id": row["device_id"],
                    "relay_url": row["relay_server_url"],
                    "last_heartbeat_at": row["last_heartbeat_at"].isoformat()
                        if row["last_heartbeat_at"] else None,
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"get_mesh_peers failed: {e}")
            return []

    async def get_mesh_stats(self, device_id: str) -> dict:
        """Get mesh relay stats for a device."""
        db = self.persistence
        if not hasattr(db, 'pool'):
            return {"device_id": device_id, "relayed_for_others": 0, "saved_by_peers": 0, "total_relay_hops": 0, "last_relay_at": None}
        try:
            async with db.pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT
                        COUNT(*) FILTER (WHERE relay_device_id = $1)   AS relayed_for_others,
                        COUNT(*) FILTER (WHERE device_id = $1 AND relay_device_id IS NOT NULL) AS saved_by_peers,
                        COALESCE(SUM(hop_count) FILTER (WHERE relay_device_id = $1), 0) AS total_relay_hops,
                        MAX(relayed_at) FILTER (WHERE relay_device_id = $1) AS last_relay_at
                    FROM saf_transactions
                    WHERE device_id = $1 OR relay_device_id = $1
                """, device_id)
                if row is None:
                    return {"device_id": device_id, "relayed_for_others": 0, "saved_by_peers": 0, "total_relay_hops": 0, "last_relay_at": None}
                return {
                    "device_id": device_id,
                    "relayed_for_others": row["relayed_for_others"] or 0,
                    "saved_by_peers": row["saved_by_peers"] or 0,
                    "total_relay_hops": int(row["total_relay_hops"] or 0),
                    "last_relay_at": row["last_relay_at"].isoformat() if row["last_relay_at"] else None,
                }
        except Exception as e:
            logger.error(f"get_mesh_stats failed: {e}")
            return {"device_id": device_id, "relayed_for_others": 0, "saved_by_peers": 0, "total_relay_hops": 0, "last_relay_at": None}

    async def get_mesh_topology(self) -> dict:
        """Get fleet mesh topology — relay edges and node stats."""
        db = self.persistence
        now_iso = datetime.utcnow().isoformat()
        if not hasattr(db, 'pool'):
            return {"nodes": [], "edges": [], "generated_at": now_iso}
        try:
            async with db.pool.acquire() as conn:
                edge_rows = await conn.fetch("""
                    SELECT relay_source_device_id AS source_device_id,
                           relay_device_id,
                           COUNT(*) AS relay_count,
                           AVG(hop_count)::float AS avg_hop_count
                    FROM saf_transactions
                    WHERE relay_device_id IS NOT NULL
                      AND relay_source_device_id IS NOT NULL
                    GROUP BY relay_source_device_id, relay_device_id
                    ORDER BY relay_count DESC
                    LIMIT 200
                """)
                if not edge_rows:
                    return {"nodes": [], "edges": [], "generated_at": now_iso}

                # Collect all device IDs from edges
                device_ids = set()
                for row in edge_rows:
                    device_ids.add(row["source_device_id"])
                    device_ids.add(row["relay_device_id"])

                # Fetch device types + RUVON fields (relay_server_url, mesh_advisory)
                device_type_map = {}
                relay_url_map = {}
                advisory_map = {}
                if device_ids:
                    dev_rows = await conn.fetch(
                        """SELECT device_id, device_type, relay_server_url, mesh_advisory
                           FROM edge_devices WHERE device_id = ANY($1::text[])""",
                        list(device_ids)
                    )
                    for dr in dev_rows:
                        did = dr["device_id"]
                        device_type_map[did] = dr["device_type"]
                        relay_url_map[did] = dr["relay_server_url"]
                        raw_adv = dr["mesh_advisory"]
                        if raw_adv:
                            try:
                                advisory_map[did] = json.loads(raw_adv)
                            except Exception:
                                pass

                # Build per-node stats
                node_stats = {}
                for did in device_ids:
                    node_stats[did] = {"relayed_for_others": 0, "saved_by_peers": 0}
                for row in edge_rows:
                    node_stats[row["relay_device_id"]]["relayed_for_others"] += row["relay_count"]
                    node_stats[row["source_device_id"]]["saved_by_peers"] += row["relay_count"]

                max_relay = max((v["relayed_for_others"] for v in node_stats.values()), default=1) or 1
                nodes = [
                    {
                        "device_id": did,
                        "device_type": device_type_map.get(did, "pos"),
                        "relayed_for_others": stats["relayed_for_others"],
                        "saved_by_peers": stats["saved_by_peers"],
                        "relay_score": round(stats["relayed_for_others"] / max_relay, 4),
                        # RUVON Phase 5 fields
                        "relay_server_url": relay_url_map.get(did),
                        "vector_score": advisory_map.get(did, {}).get("relay_score"),
                        "connectivity_quality": advisory_map.get(did, {}).get("connectivity_quality"),
                        "known_peers": advisory_map.get(did, {}).get("known_peers"),
                        "is_local_master": advisory_map.get(did, {}).get("is_local_master", False),
                    }
                    for did, stats in node_stats.items()
                ]
                edges = [
                    {
                        "source_device_id": row["source_device_id"],
                        "relay_device_id": row["relay_device_id"],
                        "relay_count": row["relay_count"],
                        "avg_hop_count": round(row["avg_hop_count"] or 1.0, 2),
                    }
                    for row in edge_rows
                ]
                return {"nodes": nodes, "edges": edges, "generated_at": now_iso}
        except Exception as e:
            logger.error(f"get_mesh_topology failed: {e}")
            return {"nodes": [], "edges": [], "generated_at": now_iso}
