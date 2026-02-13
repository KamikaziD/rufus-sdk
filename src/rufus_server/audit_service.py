"""
Audit Service

Manages audit log recording, querying, and compliance reporting.
"""

import logging
import json
import csv
import io
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import uuid4

from .audit import (
    AuditEvent,
    AuditQuery,
    AuditLogEntry,
    AuditQueryResult,
    AuditExportFormat,
    AuditRetentionPolicy,
    EventType,
    ActorType,
    get_compliance_tags
)

logger = logging.getLogger(__name__)


class AuditService:
    """Service for audit logging and compliance tracking."""

    def __init__(self, persistence):
        self.persistence = persistence

    async def log_event(self, event: AuditEvent) -> str:
        """
        Log an audit event.

        Args:
            event: Audit event to log

        Returns:
            audit_id: Unique audit event identifier
        """
        audit_id = str(uuid4())

        # Add compliance tags if not provided
        if not event.compliance_tags:
            event.compliance_tags = get_compliance_tags(event.event_type, event.command_type)

        # Insert audit record
        async with self.persistence.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO command_audit_log (
                    audit_id, event_type, command_id, broadcast_id, batch_id, schedule_id,
                    device_id, device_type, merchant_id, command_type, command_data,
                    actor_type, actor_id, actor_ip, user_agent,
                    status, result_data, error_message,
                    duration_ms, session_id, request_id, parent_audit_id,
                    data_region, compliance_tags
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15,
                    $16, $17, $18, $19, $20, $21, $22, $23, $24
                )
                """,
                audit_id,
                event.event_type.value,
                event.command_id,
                event.broadcast_id,
                event.batch_id,
                event.schedule_id,
                event.device_id,
                event.device_type,
                event.merchant_id,
                event.command_type,
                json.dumps(event.command_data),
                event.actor_type.value,
                event.actor_id,
                event.actor_ip,
                event.user_agent,
                event.status,
                json.dumps(event.result_data),
                event.error_message,
                event.duration_ms,
                event.session_id,
                event.request_id,
                event.parent_audit_id,
                event.data_region,
                json.dumps(event.compliance_tags)
            )

        logger.debug(
            f"Logged audit event {audit_id}: {event.event_type.value} "
            f"(device={event.device_id}, actor={event.actor_id})"
        )

        return audit_id

    async def query_logs(self, query: AuditQuery) -> AuditQueryResult:
        """
        Query audit logs with filters.

        Args:
            query: Query parameters

        Returns:
            Query results with entries and pagination info
        """
        async with self.persistence.pool.acquire() as conn:
            # Build WHERE clause
            conditions = []
            params = []
            param_count = 0

            # Time range
            if query.start_time:
                param_count += 1
                conditions.append(f"timestamp >= ${param_count}")
                params.append(query.start_time)

            if query.end_time:
                param_count += 1
                conditions.append(f"timestamp <= ${param_count}")
                params.append(query.end_time)

            # Entity filters
            if query.device_id:
                param_count += 1
                conditions.append(f"device_id = ${param_count}")
                params.append(query.device_id)

            if query.merchant_id:
                param_count += 1
                conditions.append(f"merchant_id = ${param_count}")
                params.append(query.merchant_id)

            if query.command_id:
                param_count += 1
                conditions.append(f"command_id = ${param_count}")
                params.append(query.command_id)

            if query.broadcast_id:
                param_count += 1
                conditions.append(f"broadcast_id = ${param_count}")
                params.append(query.broadcast_id)

            if query.batch_id:
                param_count += 1
                conditions.append(f"batch_id = ${param_count}")
                params.append(query.batch_id)

            if query.schedule_id:
                param_count += 1
                conditions.append(f"schedule_id = ${param_count}")
                params.append(query.schedule_id)

            # Event filters
            if query.event_types:
                param_count += 1
                conditions.append(f"event_type = ANY(${param_count})")
                params.append(query.event_types)

            if query.command_types:
                param_count += 1
                conditions.append(f"command_type = ANY(${param_count})")
                params.append(query.command_types)

            if query.actor_type:
                param_count += 1
                conditions.append(f"actor_type = ${param_count}")
                params.append(query.actor_type)

            if query.actor_id:
                param_count += 1
                conditions.append(f"actor_id = ${param_count}")
                params.append(query.actor_id)

            # Status filter
            if query.status:
                param_count += 1
                conditions.append(f"status = ${param_count}")
                params.append(query.status)

            # Full-text search
            if query.search_text:
                param_count += 1
                conditions.append(f"searchable_text @@ plainto_tsquery('english', ${param_count})")
                params.append(query.search_text)

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            # Get total count
            count_result = await conn.fetchval(
                f"SELECT COUNT(*) FROM command_audit_log WHERE {where_clause}",
                *params
            )

            # Get paginated results
            param_count += 1
            params.append(query.limit)
            param_count += 1
            params.append(query.offset)

            # Determine sort order
            order_direction = "DESC" if query.order_direction.lower() == "desc" else "ASC"

            rows = await conn.fetch(
                f"""
                SELECT
                    audit_id, event_type, command_id, broadcast_id, batch_id, schedule_id,
                    device_id, device_type, merchant_id, command_type, command_data,
                    actor_type, actor_id, actor_ip, user_agent,
                    status, result_data, error_message,
                    timestamp, duration_ms, session_id, request_id, parent_audit_id,
                    data_region, compliance_tags
                FROM command_audit_log
                WHERE {where_clause}
                ORDER BY {query.order_by} {order_direction}
                LIMIT ${param_count - 1} OFFSET ${param_count}
                """,
                *params
            )

            entries = [
                AuditLogEntry(
                    audit_id=row["audit_id"],
                    event_type=row["event_type"],
                    command_id=row["command_id"],
                    broadcast_id=row["broadcast_id"],
                    batch_id=row["batch_id"],
                    schedule_id=row["schedule_id"],
                    device_id=row["device_id"],
                    device_type=row["device_type"],
                    merchant_id=row["merchant_id"],
                    command_type=row["command_type"],
                    command_data=json.loads(row["command_data"]) if row["command_data"] else {},
                    actor_type=row["actor_type"],
                    actor_id=row["actor_id"],
                    actor_ip=row["actor_ip"],
                    user_agent=row["user_agent"],
                    status=row["status"],
                    result_data=json.loads(row["result_data"]) if row["result_data"] else {},
                    error_message=row["error_message"],
                    timestamp=row["timestamp"],
                    duration_ms=row["duration_ms"],
                    session_id=row["session_id"],
                    request_id=row["request_id"],
                    parent_audit_id=row["parent_audit_id"],
                    data_region=row["data_region"],
                    compliance_tags=json.loads(row["compliance_tags"]) if row["compliance_tags"] else []
                )
                for row in rows
            ]

            return AuditQueryResult(
                entries=entries,
                total_count=count_result,
                limit=query.limit,
                offset=query.offset,
                has_more=(query.offset + query.limit) < count_result
            )

    async def export_logs(
        self,
        query: AuditQuery,
        export_format: AuditExportFormat = AuditExportFormat.JSON
    ) -> str:
        """
        Export audit logs in specified format.

        Args:
            query: Query parameters
            export_format: Export format (JSON, CSV, JSONL)

        Returns:
            Formatted export data as string
        """
        # Query logs (increase limit for export)
        query.limit = min(query.limit, 10000)  # Cap at 10k for safety
        result = await self.query_logs(query)

        if export_format == AuditExportFormat.JSON:
            return self._export_json(result.entries)
        elif export_format == AuditExportFormat.CSV:
            return self._export_csv(result.entries)
        elif export_format == AuditExportFormat.JSONL:
            return self._export_jsonl(result.entries)

    def _export_json(self, entries: List[AuditLogEntry]) -> str:
        """Export as JSON array."""
        data = [entry.dict() for entry in entries]
        # Convert datetime to ISO format
        for entry in data:
            if entry.get("timestamp"):
                entry["timestamp"] = entry["timestamp"].isoformat()
        return json.dumps(data, indent=2)

    def _export_csv(self, entries: List[AuditLogEntry]) -> str:
        """Export as CSV."""
        if not entries:
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "audit_id", "timestamp", "event_type", "command_type",
                "device_id", "merchant_id", "actor_type", "actor_id",
                "status", "error_message", "compliance_tags"
            ]
        )
        writer.writeheader()

        for entry in entries:
            writer.writerow({
                "audit_id": entry.audit_id,
                "timestamp": entry.timestamp.isoformat(),
                "event_type": entry.event_type,
                "command_type": entry.command_type or "",
                "device_id": entry.device_id or "",
                "merchant_id": entry.merchant_id or "",
                "actor_type": entry.actor_type,
                "actor_id": entry.actor_id,
                "status": entry.status or "",
                "error_message": entry.error_message or "",
                "compliance_tags": ",".join(entry.compliance_tags)
            })

        return output.getvalue()

    def _export_jsonl(self, entries: List[AuditLogEntry]) -> str:
        """Export as JSON Lines (one JSON object per line)."""
        lines = []
        for entry in entries:
            data = entry.dict()
            if data.get("timestamp"):
                data["timestamp"] = data["timestamp"].isoformat()
            lines.append(json.dumps(data))
        return "\n".join(lines)

    async def get_retention_policy(self, policy_name: str) -> Optional[AuditRetentionPolicy]:
        """Get audit retention policy."""
        async with self.persistence.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT policy_name, retention_days, event_types,
                       archive_before_delete, archive_location, is_active
                FROM audit_retention_policies
                WHERE policy_name = $1
                """,
                policy_name
            )

            if not row:
                return None

            return AuditRetentionPolicy(
                policy_name=row["policy_name"],
                retention_days=row["retention_days"],
                event_types=json.loads(row["event_types"]) if row["event_types"] else [],
                archive_before_delete=row["archive_before_delete"],
                archive_location=row["archive_location"],
                is_active=row["is_active"]
            )

    async def cleanup_old_logs(self, policy_name: str = "pci_compliance_default") -> Dict[str, int]:
        """
        Clean up old audit logs according to retention policy.

        Args:
            policy_name: Retention policy to apply

        Returns:
            Statistics about cleanup operation
        """
        policy = await self.get_retention_policy(policy_name)
        if not policy or not policy.is_active:
            logger.warning(f"Retention policy {policy_name} not found or inactive")
            return {"deleted": 0, "archived": 0}

        cutoff_date = datetime.utcnow() - timedelta(days=policy.retention_days)

        async with self.persistence.pool.acquire() as conn:
            # Count logs to delete
            if policy.event_types:
                count = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM command_audit_log
                    WHERE timestamp < $1 AND event_type = ANY($2)
                    """,
                    cutoff_date,
                    policy.event_types
                )
            else:
                count = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM command_audit_log
                    WHERE timestamp < $1
                    """,
                    cutoff_date
                )

            if count == 0:
                logger.info(f"No logs to clean up (policy: {policy_name})")
                return {"deleted": 0, "archived": 0}

            # TODO: Archive logs if policy.archive_before_delete is True
            # This would involve exporting to S3, archive storage, etc.
            archived = 0
            if policy.archive_before_delete:
                logger.warning("Archive functionality not yet implemented - skipping archive")
                # archived = await self._archive_logs(cutoff_date, policy)

            # Delete old logs
            if policy.event_types:
                result = await conn.execute(
                    """
                    DELETE FROM command_audit_log
                    WHERE timestamp < $1 AND event_type = ANY($2)
                    """,
                    cutoff_date,
                    policy.event_types
                )
            else:
                result = await conn.execute(
                    """
                    DELETE FROM command_audit_log
                    WHERE timestamp < $1
                    """,
                    cutoff_date
                )

            deleted = int(result.split()[-1])

            logger.info(
                f"Cleaned up {deleted} audit logs (policy: {policy_name}, "
                f"cutoff: {cutoff_date.isoformat()})"
            )

            return {"deleted": deleted, "archived": archived}
