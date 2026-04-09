"""
EdgeWorkflowSyncer — push completed edge workflows to cloud, purge local SQLite.

Runs inside _sync_loop() of RuvonEdgeAgent when online. Queries terminal-status
workflows from SQLite, POSTs them to the cloud, then deletes the synced rows to
prevent local DB bloat (offline-card-machine pattern).
"""
import logging
import httpx
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SYNC_STATE_KEY = "last_workflow_sync_at"


class EdgeWorkflowSyncer:
    """
    Syncs completed edge workflow executions + audit logs to the cloud control plane.

    One call to sync() covers a full cycle:
      1. Query SQLite for terminal workflows since last_sync_at
      2. Fetch associated audit log rows
      3. POST batch to /api/v1/devices/{device_id}/sync/workflows
      4. On success: delete synced rows + update last_sync_at
      5. On failure: leave rows in SQLite (retry next cycle)
    """

    def __init__(
        self,
        persistence,
        cloud_url: str,
        device_id: str,
        api_key: str,
        batch_size: int = 100,
    ):
        self.persistence = persistence
        self.cloud_url = cloud_url.rstrip("/")
        self.device_id = device_id
        self.api_key = api_key or ""
        self.batch_size = batch_size

    # 5 MB hard cap — if payload exceeds this, drop audit logs and sync workflow records only
    _MAX_PAYLOAD_BYTES = 5 * 1024 * 1024

    async def sync(self) -> dict:
        """One sync cycle: query → push → purge. Returns summary dict.

        Idempotency is provided by deletion, not timestamps: completed rows are
        removed from SQLite once the cloud acknowledges them, so a full scan
        every cycle is correct and efficient — no watermark needed.
        """
        workflows = await self.persistence.get_pending_sync_workflows(limit=self.batch_size)
        if not workflows:
            return {"synced": 0, "purged": 0}

        workflow_ids = [w["id"] for w in workflows]
        audit_logs = await self.persistence.get_audit_logs_for_workflows(
            workflow_ids, limit_per_workflow=50
        )

        import json as _json
        payload = {"workflows": workflows, "audit_logs": audit_logs}
        payload_bytes = _json.dumps(payload).encode()
        if len(payload_bytes) > self._MAX_PAYLOAD_BYTES:
            logger.warning(
                f"[WorkflowSync] Payload {len(payload_bytes)} bytes exceeds 5 MB cap — "
                "dropping audit logs to reduce size"
            )
            payload = {"workflows": workflows, "audit_logs": []}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.cloud_url}/api/v1/devices/{self.device_id}/sync/workflows",
                    json=payload,
                    headers={"X-API-Key": self.api_key},
                )

            if resp.status_code not in (200, 201):
                logger.warning(
                    f"[WorkflowSync] Server returned {resp.status_code}: {resp.text[:200]}"
                )
                return {"synced": 0, "purged": 0, "error": resp.status_code}

            result = resp.json()
            accepted_ids = result.get("accepted_workflow_ids", workflow_ids)

        except Exception as exc:
            logger.warning(f"[WorkflowSync] Push failed (will retry next cycle): {exc}")
            return {"synced": 0, "purged": 0, "error": str(exc)}

        purged = await self.persistence.delete_synced_workflows(accepted_ids)

        logger.info(
            f"[WorkflowSync] Synced {len(accepted_ids)} workflows "
            f"({len(audit_logs)} audit rows), purged {purged} local records"
        )
        return {
            "synced": len(accepted_ids),
            "purged": purged,
            "audit_rows": len(audit_logs),
        }
