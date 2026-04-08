"""Webhook notification service for Ruvon Edge Cloud Control Plane."""

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4
from enum import Enum

import httpx
from pydantic import BaseModel, HttpUrl

logger = logging.getLogger(__name__)


class WebhookEvent(str, Enum):
    """Webhook event types."""
    # Device events
    DEVICE_REGISTERED = "device.registered"
    DEVICE_ONLINE = "device.online"
    DEVICE_OFFLINE = "device.offline"
    DEVICE_ERROR = "device.error"

    # Command events
    COMMAND_CREATED = "command.created"
    COMMAND_SENT = "command.sent"
    COMMAND_COMPLETED = "command.completed"
    COMMAND_FAILED = "command.failed"
    COMMAND_EXPIRED = "command.expired"

    # Transaction events (SAF)
    TRANSACTION_SYNCED = "transaction.synced"
    TRANSACTION_APPROVED = "transaction.approved"
    TRANSACTION_DECLINED = "transaction.declined"

    # Config events
    CONFIG_UPDATED = "config.updated"
    CONFIG_DEPLOYED = "config.deployed"

    # Policy events
    POLICY_CREATED = "policy.created"
    POLICY_ACTIVATED = "policy.activated"
    POLICY_DEACTIVATED = "policy.deactivated"

    # Workflow events
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"


class WebhookStatus(str, Enum):
    """Webhook delivery status."""
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


class WebhookRegistration(BaseModel):
    """Webhook registration model."""
    id: Optional[str] = None
    webhook_id: str
    name: str
    url: HttpUrl
    events: List[WebhookEvent]
    secret: Optional[str] = None
    headers: Dict[str, str] = {}
    retry_policy: Optional[Dict[str, Any]] = None
    is_active: bool = True
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class WebhookDelivery(BaseModel):
    """Webhook delivery record."""
    id: Optional[str] = None
    webhook_id: str
    event_type: WebhookEvent
    event_data: Dict[str, Any]
    status: WebhookStatus = WebhookStatus.PENDING
    http_status: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    attempt_count: int = 0
    delivered_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class WebhookService:
    """Service for managing webhook registrations and deliveries."""

    def __init__(self, persistence, http_client: Optional[httpx.AsyncClient] = None):
        """
        Initialize webhook service.

        Args:
            persistence: Database persistence provider
            http_client: Optional HTTP client for webhook calls
        """
        self.persistence = persistence
        self.http_client = http_client or httpx.AsyncClient(timeout=30.0)
        self._is_postgres = hasattr(persistence, 'pool')

    async def _execute(self, query: str, *args):
        """Execute query on appropriate database."""
        if self._is_postgres:
            async with self.persistence.pool.acquire() as conn:
                return await conn.execute(query, *args)
        else:  # SQLite
            async with self.persistence.conn.execute(query, args):
                pass
            await self.persistence.conn.commit()

    async def _fetchrow(self, query: str, *args):
        """Fetch single row from appropriate database."""
        if self._is_postgres:
            async with self.persistence.pool.acquire() as conn:
                return await conn.fetchrow(query, *args)
        else:  # SQLite
            async with self.persistence.conn.execute(query, args) as cursor:
                row = await cursor.fetchone()
                if row:
                    columns = [desc[0] for desc in cursor.description]
                    return dict(zip(columns, row))
                return None

    async def _fetch(self, query: str, *args):
        """Fetch multiple rows from appropriate database."""
        if self._is_postgres:
            async with self.persistence.pool.acquire() as conn:
                return await conn.fetch(query, *args)
        else:  # SQLite
            async with self.persistence.conn.execute(query, args) as cursor:
                rows = await cursor.fetchall()
                if rows:
                    columns = [desc[0] for desc in cursor.description]
                    return [dict(zip(columns, row)) for row in rows]
                return []

    async def register_webhook(self, registration: WebhookRegistration) -> str:
        """
        Register a new webhook.

        Args:
            registration: WebhookRegistration data

        Returns:
            Webhook ID
        """
        webhook_id = registration.webhook_id or str(uuid4())

        if self._is_postgres:
            query = """
                INSERT INTO webhook_registrations (
                    id, webhook_id, name, url, events, secret, headers,
                    retry_policy, is_active, created_by, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW(), NOW())
            """
            await self._execute(
                query,
                str(uuid4()),
                webhook_id,
                registration.name,
                str(registration.url),
                json.dumps([e.value for e in registration.events]),
                registration.secret,
                json.dumps(registration.headers),
                json.dumps(registration.retry_policy) if registration.retry_policy else None,
                registration.is_active,
                registration.created_by
            )
        else:  # SQLite
            query = """
                INSERT INTO webhook_registrations (
                    id, webhook_id, name, url, events, secret, headers,
                    retry_policy, is_active, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
            await self._execute(
                query,
                str(uuid4()),
                webhook_id,
                registration.name,
                str(registration.url),
                json.dumps([e.value for e in registration.events]),
                registration.secret,
                json.dumps(registration.headers),
                json.dumps(registration.retry_policy) if registration.retry_policy else None,
                1 if registration.is_active else 0,
                registration.created_by
            )

        logger.info(f"Registered webhook: {webhook_id} ({registration.name})")
        return webhook_id

    async def get_webhook(self, webhook_id: str) -> Optional[WebhookRegistration]:
        """Get webhook registration by ID."""
        query = """
            SELECT id, webhook_id, name, url, events, secret, headers,
                   retry_policy, is_active, created_by, created_at, updated_at
            FROM webhook_registrations
            WHERE webhook_id = ?
        """ if not self._is_postgres else """
            SELECT id, webhook_id, name, url, events, secret, headers,
                   retry_policy, is_active, created_by, created_at, updated_at
            FROM webhook_registrations
            WHERE webhook_id = $1
        """

        row = await self._fetchrow(query, webhook_id)
        if not row:
            return None

        # Parse JSON fields
        events_data = row['events']
        if not self._is_postgres and isinstance(events_data, str):
            events_data = json.loads(events_data)

        headers_data = row['headers'] or {}
        if not self._is_postgres and isinstance(headers_data, str):
            headers_data = json.loads(headers_data)

        retry_policy = row['retry_policy']
        if retry_policy and not self._is_postgres and isinstance(retry_policy, str):
            retry_policy = json.loads(retry_policy)

        return WebhookRegistration(
            id=str(row['id']),
            webhook_id=row['webhook_id'],
            name=row['name'],
            url=row['url'],
            events=[WebhookEvent(e) for e in events_data],
            secret=row['secret'],
            headers=headers_data,
            retry_policy=retry_policy,
            is_active=bool(row['is_active']) if not self._is_postgres else row['is_active'],
            created_by=row['created_by'],
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )

    async def list_webhooks(self, is_active: Optional[bool] = None) -> List[Dict[str, Any]]:
        """List all webhook registrations."""
        if is_active is not None:
            if self._is_postgres:
                query = """
                    SELECT webhook_id, name, url, events, is_active, created_at
                    FROM webhook_registrations
                    WHERE is_active = $1
                    ORDER BY created_at DESC
                """
                rows = await self._fetch(query, is_active)
            else:
                query = """
                    SELECT webhook_id, name, url, events, is_active, created_at
                    FROM webhook_registrations
                    WHERE is_active = ?
                    ORDER BY created_at DESC
                """
                rows = await self._fetch(query, 1 if is_active else 0)
        else:
            query = """
                SELECT webhook_id, name, url, events, is_active, created_at
                FROM webhook_registrations
                ORDER BY created_at DESC
            """
            rows = await self._fetch(query)

        result = []
        for row in rows:
            events_data = row['events']
            if not self._is_postgres and isinstance(events_data, str):
                events_data = json.loads(events_data)

            result.append({
                'webhook_id': row['webhook_id'],
                'name': row['name'],
                'url': row['url'],
                'events': events_data,
                'is_active': bool(row['is_active']) if not self._is_postgres else row['is_active'],
                'created_at': row['created_at']
            })

        return result

    async def update_webhook(self, webhook_id: str, updates: Dict[str, Any]) -> bool:
        """Update webhook registration."""
        allowed_fields = ["name", "url", "events", "secret", "headers", "retry_policy", "is_active"]
        update_fields = {k: v for k, v in updates.items() if k in allowed_fields}

        if not update_fields:
            return False

        set_clauses = []
        params = []
        param_idx = 1

        for field, value in update_fields.items():
            if field == "events":
                value = json.dumps([e.value if isinstance(e, WebhookEvent) else e for e in value])
            elif field in ["headers", "retry_policy"]:
                value = json.dumps(value) if value else None
            elif field == "is_active" and not self._is_postgres:
                value = 1 if value else 0

            if self._is_postgres:
                set_clauses.append(f"{field} = ${param_idx}")
            else:
                set_clauses.append(f"{field} = ?")
            params.append(value)
            param_idx += 1

        # Add updated_at
        if self._is_postgres:
            set_clauses.append(f"updated_at = NOW()")
        else:
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")

        params.append(webhook_id)

        if self._is_postgres:
            query = f"""
                UPDATE webhook_registrations
                SET {', '.join(set_clauses)}
                WHERE webhook_id = ${param_idx}
            """
        else:
            query = f"""
                UPDATE webhook_registrations
                SET {', '.join(set_clauses)}
                WHERE webhook_id = ?
            """

        await self._execute(query, *params)
        return True

    async def delete_webhook(self, webhook_id: str) -> bool:
        """Delete webhook registration."""
        query = "DELETE FROM webhook_registrations WHERE webhook_id = ?"
        if self._is_postgres:
            query = "DELETE FROM webhook_registrations WHERE webhook_id = $1"

        await self._execute(query, webhook_id)
        logger.info(f"Deleted webhook: {webhook_id}")
        return True

    async def dispatch_event(
        self,
        event_type: WebhookEvent,
        event_data: Dict[str, Any]
    ) -> int:
        """
        Dispatch event to all subscribed webhooks.

        Args:
            event_type: Event type
            event_data: Event payload

        Returns:
            Number of webhooks triggered
        """
        # Find webhooks subscribed to this event
        if self._is_postgres:
            query = """
                SELECT webhook_id, url, secret, headers, retry_policy
                FROM webhook_registrations
                WHERE is_active = true AND events::jsonb @> $1::jsonb
            """
            params = [json.dumps([event_type.value])]
        else:
            # SQLite: Simplified query (load all and filter in Python)
            query = """
                SELECT webhook_id, url, secret, headers, retry_policy, events
                FROM webhook_registrations
                WHERE is_active = 1
            """
            params = []

        rows = await self._fetch(query, *params)

        # Filter for SQLite
        if not self._is_postgres:
            filtered_rows = []
            for row in rows:
                events = row['events']
                if isinstance(events, str):
                    events = json.loads(events)
                if event_type.value in events:
                    filtered_rows.append(row)
            rows = filtered_rows

        dispatched = 0
        for row in rows:
            webhook_id = row['webhook_id']

            # Create delivery record
            delivery_id = str(uuid4())

            if self._is_postgres:
                await self._execute(
                    """
                    INSERT INTO webhook_deliveries (
                        id, webhook_id, event_type, event_data, status, created_at
                    ) VALUES ($1, $2, $3, $4, 'pending', NOW())
                    """,
                    delivery_id,
                    webhook_id,
                    event_type.value,
                    json.dumps(event_data)
                )
            else:
                await self._execute(
                    """
                    INSERT INTO webhook_deliveries (
                        id, webhook_id, event_type, event_data, status, created_at
                    ) VALUES (?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)
                    """,
                    delivery_id,
                    webhook_id,
                    event_type.value,
                    json.dumps(event_data)
                )

            # Deliver webhook (async, non-blocking)
            try:
                await self._deliver_webhook(
                    delivery_id,
                    webhook_id,
                    row['url'],
                    event_type,
                    event_data,
                    row.get('secret'),
                    row.get('headers')
                )
                dispatched += 1
            except Exception as e:
                logger.error(f"Failed to dispatch webhook {webhook_id}: {e}")

        logger.info(f"Dispatched {event_type.value} to {dispatched} webhooks")
        return dispatched

    async def _deliver_webhook(
        self,
        delivery_id: str,
        webhook_id: str,
        url: str,
        event_type: WebhookEvent,
        event_data: Dict[str, Any],
        secret: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None
    ):
        """Deliver webhook to endpoint."""
        payload = {
            "event": event_type.value,
            "data": event_data,
            "timestamp": datetime.utcnow().isoformat(),
            "webhook_id": webhook_id
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Rufus-Edge-Webhook/1.0"
        }

        # Add custom headers (SQLite returns JSON columns as strings)
        if custom_headers:
            if isinstance(custom_headers, str):
                custom_headers = json.loads(custom_headers)
            headers.update(custom_headers)

        # Add HMAC signature
        if secret:
            signature = self._compute_signature(payload, secret)
            headers["X-Rufus-Signature"] = signature

        try:
            response = await self.http_client.post(
                url,
                json=payload,
                headers=headers,
                timeout=30.0
            )

            # Update delivery status
            if self._is_postgres:
                await self._execute(
                    """
                    UPDATE webhook_deliveries
                    SET status = $1, http_status = $2, response_body = $3,
                        attempt_count = attempt_count + 1, delivered_at = NOW()
                    WHERE id = $4
                    """,
                    "delivered" if response.status_code < 400 else "failed",
                    response.status_code,
                    response.text[:1000],  # Limit response body
                    delivery_id
                )
            else:
                await self._execute(
                    """
                    UPDATE webhook_deliveries
                    SET status = ?, http_status = ?, response_body = ?,
                        attempt_count = attempt_count + 1, delivered_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    "delivered" if response.status_code < 400 else "failed",
                    response.status_code,
                    response.text[:1000],
                    delivery_id
                )

            logger.info(f"Webhook delivered: {webhook_id} -> {url} ({response.status_code})")

        except Exception as e:
            # Update delivery status with error
            if self._is_postgres:
                await self._execute(
                    """
                    UPDATE webhook_deliveries
                    SET status = 'failed', error_message = $1, attempt_count = attempt_count + 1
                    WHERE id = $2
                    """,
                    str(e)[:500],
                    delivery_id
                )
            else:
                await self._execute(
                    """
                    UPDATE webhook_deliveries
                    SET status = 'failed', error_message = ?, attempt_count = attempt_count + 1
                    WHERE id = ?
                    """,
                    str(e)[:500],
                    delivery_id
                )

            logger.error(f"Webhook delivery failed: {webhook_id} -> {url}: {e}")

    def _compute_signature(self, payload: Dict[str, Any], secret: str) -> str:
        """Compute HMAC signature for webhook payload."""
        payload_bytes = json.dumps(payload, sort_keys=True).encode('utf-8')
        signature = hmac.new(
            secret.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"

    async def get_delivery_history(
        self,
        webhook_id: Optional[str] = None,
        status: Optional[WebhookStatus] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get webhook delivery history."""
        conditions = []
        params = []
        param_idx = 1

        if webhook_id:
            if self._is_postgres:
                conditions.append(f"webhook_id = ${param_idx}")
            else:
                conditions.append("webhook_id = ?")
            params.append(webhook_id)
            param_idx += 1

        if status:
            if self._is_postgres:
                conditions.append(f"status = ${param_idx}")
            else:
                conditions.append("status = ?")
            params.append(status.value)
            param_idx += 1

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        if self._is_postgres:
            query = f"""
                SELECT id, webhook_id, event_type, event_data, status,
                       http_status, error_message, attempt_count, delivered_at, created_at
                FROM webhook_deliveries
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ${param_idx}
            """
        else:
            query = f"""
                SELECT id, webhook_id, event_type, event_data, status,
                       http_status, error_message, attempt_count, delivered_at, created_at
                FROM webhook_deliveries
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
            """

        params.append(limit)
        rows = await self._fetch(query, *params)

        result = []
        for row in rows:
            event_data = row['event_data']
            if not self._is_postgres and isinstance(event_data, str):
                event_data = json.loads(event_data)

            result.append({
                'id': str(row['id']),
                'webhook_id': row['webhook_id'],
                'event_type': row['event_type'],
                'event_data': event_data,
                'status': row['status'],
                'http_status': row['http_status'],
                'error_message': row['error_message'],
                'attempt_count': row['attempt_count'],
                'delivered_at': row['delivered_at'],
                'created_at': row['created_at']
            })

        return result

    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()
