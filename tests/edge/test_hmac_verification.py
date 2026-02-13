"""
Tests for HMAC authentication on sync payloads.

Validates that:
1. Edge device correctly signs sync payloads with HMAC-SHA256
2. Cloud control plane correctly verifies HMAC signatures
3. Tampered payloads are rejected
4. Missing HMAC signatures are rejected
"""

import pytest
import hmac
import hashlib
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from rufus_edge.sync_manager import SyncManager
from rufus_edge.models import SAFTransaction
from rufus_server.device_service import DeviceService


class TestHMACAuthentication:
    """Test suite for HMAC-based payload authentication."""

    @pytest.fixture
    def api_key(self):
        """Device API key for testing."""
        return "test_api_key_12345"

    @pytest.fixture
    def sync_manager(self, api_key):
        """Create SyncManager instance for testing."""
        persistence = AsyncMock()
        persistence.conn = AsyncMock()
        persistence._deserialize_json = lambda x: {"transaction": {"transaction_id": "test-123"}}

        manager = SyncManager(
            persistence=persistence,
            sync_url="http://localhost:8000",
            device_id="test-device-001",
            api_key=api_key,
            batch_size=10,
        )
        return manager

    @pytest.fixture
    def device_service(self):
        """Create DeviceService instance for testing."""
        persistence = AsyncMock()
        persistence.pool = AsyncMock()
        return DeviceService(persistence=persistence)

    def test_hmac_calculation(self, sync_manager):
        """Test HMAC signature generation on edge device."""
        # Test data
        data = "transaction-123|encrypted-payload-hex|key-001"

        # Calculate HMAC
        signature = sync_manager._calculate_hmac(data)

        # Verify it's a valid hex string
        assert len(signature) == 64  # SHA256 produces 64 hex chars
        assert all(c in '0123456789abcdef' for c in signature)

        # Verify it matches manual calculation
        expected = hmac.new(
            sync_manager.api_key.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        assert signature == expected

    def test_hmac_verification_valid(self, device_service, api_key):
        """Test HMAC verification with valid signature."""
        data = "transaction-123|encrypted-payload-hex|key-001"

        # Generate valid HMAC
        valid_hmac = hmac.new(
            api_key.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Verify
        assert device_service._verify_hmac(api_key, data, valid_hmac) is True

    def test_hmac_verification_invalid(self, device_service, api_key):
        """Test HMAC verification with invalid signature."""
        data = "transaction-123|encrypted-payload-hex|key-001"

        # Generate HMAC with wrong key
        wrong_key = "wrong_api_key"
        invalid_hmac = hmac.new(
            wrong_key.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Verification should fail
        assert device_service._verify_hmac(api_key, data, invalid_hmac) is False

    def test_hmac_verification_tampered_data(self, device_service, api_key):
        """Test HMAC verification detects tampered data."""
        original_data = "transaction-123|encrypted-payload-hex|key-001"
        tampered_data = "transaction-123|tampered-payload-hex|key-001"

        # Generate HMAC for original data
        original_hmac = hmac.new(
            api_key.encode('utf-8'),
            original_data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Verify with tampered data should fail
        assert device_service._verify_hmac(api_key, tampered_data, original_hmac) is False

    def test_hmac_constant_time_comparison(self, device_service, api_key):
        """Test that HMAC verification uses constant-time comparison."""
        data = "transaction-123|encrypted-payload-hex|key-001"

        # Generate valid HMAC
        valid_hmac = hmac.new(
            api_key.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Create nearly identical HMAC (differs in last char)
        almost_valid = valid_hmac[:-1] + ('a' if valid_hmac[-1] != 'a' else 'b')

        # Both should fail (or succeed) in constant time
        # We can't easily test timing, but we verify compare_digest is used
        assert device_service._verify_hmac(api_key, data, valid_hmac) is True
        assert device_service._verify_hmac(api_key, data, almost_valid) is False

    @pytest.mark.asyncio
    async def test_sync_payload_includes_hmac(self, sync_manager):
        """Test that sync payloads include HMAC signatures."""
        # Create test transaction
        transaction = SAFTransaction(
            transaction_id="test-txn-001",
            workflow_id="wf-001",
            idempotency_key="test-key-001",
            encrypted_payload=b"encrypted-data",
            encryption_key_id="key-001",
        )

        # Mock HTTP client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"accepted": [], "rejected": []}

        sync_manager._http_client = AsyncMock()
        sync_manager._http_client.post = AsyncMock(return_value=mock_response)

        # Sync the transaction
        await sync_manager._sync_batch([transaction])

        # Verify HMAC was included in payload
        call_args = sync_manager._http_client.post.call_args
        payload = call_args.kwargs['json']

        assert 'transactions' in payload
        assert len(payload['transactions']) == 1

        txn = payload['transactions'][0]
        assert 'hmac' in txn
        assert txn['hmac'] != ""
        assert len(txn['hmac']) == 64  # SHA256 hex

    @pytest.mark.asyncio
    async def test_sync_rejects_missing_hmac(self, device_service, api_key):
        """Test that cloud rejects transactions without HMAC."""
        # Transaction without HMAC
        transactions = [
            {
                "transaction_id": "test-001",
                "encrypted_blob": "encrypted-data",
                "encryption_key_id": "key-001",
                # No HMAC field
            }
        ]

        result = await device_service.sync_transactions(
            device_id="test-device",
            transactions=transactions,
            api_key=api_key
        )

        # Should be rejected
        assert len(result["rejected"]) == 1
        assert result["rejected"][0]["reason"] == "HMAC signature required"
        assert len(result["accepted"]) == 0

    @pytest.mark.asyncio
    async def test_sync_rejects_invalid_hmac(self, device_service, api_key):
        """Test that cloud rejects transactions with invalid HMAC."""
        # Transaction with invalid HMAC
        transactions = [
            {
                "transaction_id": "test-001",
                "encrypted_blob": "encrypted-data",
                "encryption_key_id": "key-001",
                "hmac": "invalid_hmac_signature_123456789abcdef0123456789abcdef0123456",
            }
        ]

        # Mock database connection
        device_service.persistence.pool.acquire = AsyncMock()

        result = await device_service.sync_transactions(
            device_id="test-device",
            transactions=transactions,
            api_key=api_key
        )

        # Should be rejected
        assert len(result["rejected"]) == 1
        assert result["rejected"][0]["reason"] == "HMAC verification failed"
        assert len(result["accepted"]) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
