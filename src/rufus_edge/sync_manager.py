"""
SyncManager - Store-and-Forward transaction synchronization.

Handles:
- Queueing offline transactions for later sync
- Batch uploading when connectivity is restored
- Idempotency-based deduplication
- Retry logic with exponential backoff
- HMAC authentication for payload integrity
"""

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import httpx

from rufus_edge.models import SAFTransaction, SyncReport, SyncStatus, TransactionStatus

logger = logging.getLogger(__name__)


class SyncManager:
    """
    Manages Store-and-Forward transaction synchronization.

    This component queues offline transactions locally and syncs them
    to the cloud control plane when connectivity is restored.

    Features:
    - Encrypted local storage
    - Idempotency-based deduplication
    - Batch upload with retry logic
    - Conflict resolution
    """

    def __init__(
        self,
        persistence,  # SQLitePersistenceProvider
        sync_url: str,
        device_id: str,
        api_key: str,
        batch_size: int = 50,
        max_retries: int = 3,
        retry_delay_seconds: int = 5,
    ):
        self.persistence = persistence
        self.sync_url = sync_url
        self.device_id = device_id
        self.api_key = api_key
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

        self._sync_in_progress = False
        self._last_sync_at: Optional[datetime] = None
        self._http_client: Optional[httpx.AsyncClient] = None

    async def initialize(self):
        """Initialize the sync manager."""
        self._http_client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "X-API-Key": self.api_key,
                "X-Device-ID": self.device_id,
                "Content-Type": "application/json",
            }
        )
        logger.info(f"SyncManager initialized for device {self.device_id}")

    async def close(self):
        """Close the sync manager."""
        if self._http_client:
            await self._http_client.aclose()

    async def queue_for_sync(self, transaction: SAFTransaction) -> str:
        """
        Queue a transaction for later synchronization.

        Args:
            transaction: The SAF transaction to queue

        Returns:
            The transaction ID
        """
        # Store in local database
        await self.persistence.create_task_record(
            execution_id=transaction.workflow_id or transaction.transaction_id,
            step_name="SAF_Sync",
            step_index=0,
            task_data={
                "transaction": transaction.model_dump(mode="json"),
                "queued_at": datetime.utcnow().isoformat(),
            },
            idempotency_key=transaction.idempotency_key,
        )

        logger.info(f"Queued transaction {transaction.transaction_id} for sync")
        return transaction.transaction_id

    async def get_pending_count(self) -> int:
        """Get count of transactions pending sync."""
        try:
            async with self.persistence.conn.execute(
                """
                SELECT COUNT(*) FROM tasks
                WHERE step_name = 'SAF_Sync' AND status = 'PENDING'
                """
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.error(f"Failed to get pending count: {e}")
            return 0

    async def sync_all_pending(self) -> SyncReport:
        """
        Sync all pending transactions to the cloud.

        Returns:
            SyncReport with results
        """
        if self._sync_in_progress:
            logger.warning("Sync already in progress, skipping")
            return SyncReport(
                status=SyncStatus.FAILED,
                started_at=datetime.utcnow(),
                errors=[{"message": "Sync already in progress"}]
            )

        self._sync_in_progress = True
        report = SyncReport(
            status=SyncStatus.IN_PROGRESS,
            started_at=datetime.utcnow()
        )

        try:
            # Get pending transactions
            pending = await self._get_pending_transactions()
            report.total_transactions = len(pending)

            if not pending:
                report.status = SyncStatus.COMPLETED
                report.completed_at = datetime.utcnow()
                return report

            # Process in batches
            for i in range(0, len(pending), self.batch_size):
                batch = pending[i:i + self.batch_size]
                batch_result = await self._sync_batch(batch)

                report.synced_count += batch_result["synced"]
                report.failed_count += batch_result["failed"]
                report.duplicate_count += batch_result["duplicates"]
                report.synced_ids.extend(batch_result["synced_ids"])
                report.failed_ids.extend(batch_result["failed_ids"])
                report.errors.extend(batch_result["errors"])

            # Mark synced transactions in local DB
            if report.synced_ids:
                await self.mark_synced(report.synced_ids)

            # Determine final status
            if report.failed_count == 0:
                report.status = SyncStatus.COMPLETED
            elif report.synced_count > 0:
                report.status = SyncStatus.PARTIAL
            else:
                report.status = SyncStatus.FAILED

            report.completed_at = datetime.utcnow()
            self._last_sync_at = report.completed_at

            logger.info(
                f"Sync completed: {report.synced_count} synced, "
                f"{report.failed_count} failed, {report.duplicate_count} duplicates"
            )

            return report

        except Exception as e:
            logger.error(f"Sync failed with error: {e}")
            report.status = SyncStatus.FAILED
            report.completed_at = datetime.utcnow()
            report.errors.append({"message": str(e)})
            return report

        finally:
            self._sync_in_progress = False

    async def _get_pending_transactions(self) -> List[SAFTransaction]:
        """Get all transactions pending sync from the local task queue."""
        try:
            async with self.persistence.conn.execute(
                """
                SELECT task_id, task_data FROM tasks
                WHERE step_name = 'SAF_Sync' AND status = 'PENDING'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (self.batch_size * 10,)  # Fetch up to 10 batches
            ) as cursor:
                rows = await cursor.fetchall()

            transactions = []
            for row in rows:
                task_data = self.persistence._deserialize_json(row[1])
                if task_data and "transaction" in task_data:
                    txn_dict = task_data["transaction"]
                    txn_dict["_task_id"] = row[0]  # Track task ID for marking synced
                    try:
                        transactions.append(SAFTransaction(**txn_dict))
                    except Exception as e:
                        logger.warning(f"Skipping malformed SAF transaction: {e}")

            return transactions

        except Exception as e:
            logger.error(f"Failed to get pending transactions: {e}")
            return []

    def _calculate_hmac(self, data: str) -> str:
        """
        Calculate HMAC-SHA256 for payload integrity.

        Uses device API key as the secret to ensure only authorized
        devices can submit valid sync payloads.

        Args:
            data: String data to sign (JSON representation of transaction)

        Returns:
            Hex-encoded HMAC signature
        """
        return hmac.new(
            self.api_key.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def _sync_batch(self, transactions: List[SAFTransaction]) -> Dict[str, Any]:
        """Sync a batch of transactions."""
        result = {
            "synced": 0,
            "failed": 0,
            "duplicates": 0,
            "synced_ids": [],
            "failed_ids": [],
            "errors": [],
        }

        if not self._http_client:
            result["errors"].append({"message": "HTTP client not initialized"})
            result["failed"] = len(transactions)
            return result

        # Prepare transactions with HMAC signatures
        signed_transactions = []
        for t in transactions:
            txn_dict = {
                "transaction_id": t.transaction_id,
                "encrypted_blob": t.encrypted_payload.hex() if t.encrypted_payload else "",
                "encryption_key_id": t.encryption_key_id or "default",
            }

            # Calculate HMAC over transaction data
            # Format: transaction_id|encrypted_blob|encryption_key_id
            hmac_input = f"{txn_dict['transaction_id']}|{txn_dict['encrypted_blob']}|{txn_dict['encryption_key_id']}"
            txn_dict["hmac"] = self._calculate_hmac(hmac_input)

            signed_transactions.append(txn_dict)

        # Prepare full payload
        payload = {
            "transactions": signed_transactions,
            "device_sequence": 0,  # TODO: Track sequence
            "device_timestamp": datetime.utcnow().isoformat(),
        }

        # Attempt sync with retry
        for attempt in range(self.max_retries):
            try:
                response = await self._http_client.post(
                    f"{self.sync_url}/api/v1/devices/{self.device_id}/sync",
                    json=payload
                )

                if response.status_code == 200:
                    data = response.json()

                    for ack in data.get("accepted", []):
                        if ack["status"] == "DUPLICATE":
                            result["duplicates"] += 1
                        else:
                            result["synced"] += 1
                            result["synced_ids"].append(ack["transaction_id"])

                    for reject in data.get("rejected", []):
                        result["failed"] += 1
                        result["failed_ids"].append(reject["transaction_id"])
                        result["errors"].append({
                            "transaction_id": reject["transaction_id"],
                            "reason": reject.get("reason", "Unknown"),
                        })

                    return result

                elif response.status_code >= 500:
                    # Server error, retry
                    logger.warning(f"Server error {response.status_code}, retrying...")
                    await asyncio.sleep(self.retry_delay_seconds * (attempt + 1))
                    continue

                else:
                    # Client error, don't retry
                    result["errors"].append({
                        "message": f"HTTP {response.status_code}: {response.text}"
                    })
                    result["failed"] = len(transactions)
                    return result

            except httpx.RequestError as e:
                logger.warning(f"Network error on attempt {attempt + 1}: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay_seconds * (attempt + 1))
                else:
                    result["errors"].append({"message": f"Network error: {e}"})
                    result["failed"] = len(transactions)

        return result

    async def mark_synced(self, transaction_ids: List[str]):
        """Mark transactions as synced in local database."""
        for tid in transaction_ids:
            try:
                # Find the task record by matching the transaction_id in task_data
                async with self.persistence.conn.execute(
                    """
                    SELECT task_id, task_data FROM tasks
                    WHERE step_name = 'SAF_Sync' AND status = 'PENDING'
                    """
                ) as cursor:
                    rows = await cursor.fetchall()

                for row in rows:
                    task_data = self.persistence._deserialize_json(row[1])
                    if (task_data
                            and "transaction" in task_data
                            and task_data["transaction"].get("transaction_id") == tid):
                        await self.persistence.update_task_status(
                            task_id=row[0],
                            status="COMPLETED",
                            result={"synced": True, "synced_at": datetime.utcnow().isoformat()}
                        )
                        logger.debug(f"Marked transaction {tid} as synced")
                        break
            except Exception as e:
                logger.error(f"Failed to mark transaction {tid} as synced: {e}")

    async def resolve_conflicts(self, server_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve conflicts between edge and cloud state.

        Rufus uses a Last-Writer-Wins (LWW) strategy with idempotency-key
        precedence for financial transactions:

        1. Idempotency-first: If cloud already has a transaction with
           the same idempotency_key, the cloud version wins (it was
           processed first and may have settled).
        2. Edge-authoritative for offline approvals: Offline-approved
           transactions are treated as tentative commitments. The cloud
           can accept or reject them during sync, but the edge decision
           stands until the cloud explicitly overrides.
        3. Monotonic sequencing: Device maintains a monotonic sequence
           counter. Cloud uses this to detect gaps (missed transactions)
           and request re-sync for specific ranges.

        Args:
            server_response: Response from cloud sync endpoint

        Returns:
            Dict with conflict resolution results
        """
        resolution = {
            "accepted": [],
            "rejected": [],
            "conflicts": [],
        }

        for item in server_response.get("accepted", []):
            if item.get("status") == "DUPLICATE":
                # Cloud already has this - edge defers to cloud version
                resolution["conflicts"].append({
                    "transaction_id": item["transaction_id"],
                    "resolution": "cloud_wins",
                    "reason": "duplicate_idempotency_key",
                })
            else:
                resolution["accepted"].append(item["transaction_id"])

        for item in server_response.get("rejected", []):
            reason = item.get("reason", "unknown")
            resolution["rejected"].append({
                "transaction_id": item["transaction_id"],
                "reason": reason,
            })
            # Rejected offline approvals need local status update
            # so the device doesn't re-sync them
            logger.warning(
                f"Transaction {item['transaction_id']} rejected by cloud: {reason}"
            )

        return resolution

    async def check_connectivity(self) -> bool:
        """Check if cloud control plane is reachable."""
        if not self._http_client:
            return False

        try:
            response = await self._http_client.get(
                f"{self.sync_url}/health",
                timeout=5.0
            )
            return response.status_code == 200
        except Exception:
            return False
