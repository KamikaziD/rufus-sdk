"""
Tests for server-side Ed25519 payload signature verification.

Tests:
1. Server accepts valid Ed25519 signature
2. Server rejects invalid/tampered signature
3. Server accepts HMAC-only (no public key registered)
"""
import base64
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _CRYPTO_AVAILABLE, reason="cryptography not installed")


def _make_device(public_key_b64=None):
    """Return a fake device record."""
    return {
        "device_id": "test-device-001",
        "api_key_hash": "abc123",
        "public_key": public_key_b64,
        "status": "online",
    }


def _make_service(device_record):
    """Return a DeviceService with a mocked persistence pool."""
    from rufus_server.device_service import DeviceService

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.execute = AsyncMock(return_value="UPDATE 0")

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_persistence = MagicMock()
    mock_persistence.pool = mock_pool

    service = DeviceService(persistence=mock_persistence)
    service._get_device = AsyncMock(return_value=device_record)
    # authenticate_device must pass for the main flow
    service.authenticate_device = AsyncMock(return_value=True)
    return service, mock_conn


def _sign(private_key: "Ed25519PrivateKey", transactions: list) -> str:
    """Sign the canonical JSON of transactions; return base64-encoded signature."""
    payload_bytes = json.dumps(transactions, sort_keys=True).encode()
    sig = private_key.sign(payload_bytes)
    return base64.b64encode(sig).decode()


@pytest.fixture
def ed25519_keypair():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_bytes = public_key.public_bytes_raw()
    pub_b64 = base64.b64encode(pub_bytes).decode()
    return private_key, pub_b64


SAMPLE_TRANSACTIONS = [
    {
        "transaction_id": "txn-001",
        "idempotency_key": "test-device-001:txn-001",
        "encrypted_payload": "enc_data",
        "encrypted_blob": "enc_data",
        "encryption_key_id": "key-1",
        "hmac": "valid_hmac",
    }
]


@pytest.mark.asyncio
async def test_server_accepts_valid_ed25519_signature(ed25519_keypair):
    """Server accepts transactions when Ed25519 signature is valid."""
    private_key, pub_b64 = ed25519_keypair
    device = _make_device(public_key_b64=pub_b64)
    service, mock_conn = _make_service(device)

    # Sign the transactions
    signature = _sign(private_key, SAMPLE_TRANSACTIONS)

    # Patch HMAC verification to pass
    with patch.object(service, "_verify_hmac", return_value=True):
        # Also patch the DB insert to return a result row
        mock_conn.fetchrow = AsyncMock(return_value={"transaction_id": "txn-001"})

        result = await service.sync_transactions(
            device_id="test-device-001",
            transactions=SAMPLE_TRANSACTIONS,
            api_key="test-api-key",
            payload_signature=signature,
        )

    assert result["rejected"] == [] or not any(
        r.get("reason", "").startswith("Ed25519") for r in result["rejected"]
    )


@pytest.mark.asyncio
async def test_server_rejects_invalid_ed25519_signature(ed25519_keypair):
    """Server rejects transactions when Ed25519 signature is tampered."""
    private_key, pub_b64 = ed25519_keypair
    device = _make_device(public_key_b64=pub_b64)
    service, _ = _make_service(device)

    # Provide a clearly invalid base64 signature (wrong bytes)
    bad_sig = base64.b64encode(b"\x00" * 64).decode()

    result = await service.sync_transactions(
        device_id="test-device-001",
        transactions=SAMPLE_TRANSACTIONS,
        api_key="test-api-key",
        payload_signature=bad_sig,
    )

    assert result["accepted"] == []
    assert any(
        "Ed25519 signature verification failed" in r.get("reason", "")
        for r in result["rejected"]
    )


@pytest.mark.asyncio
async def test_server_accepts_hmac_only_when_no_public_key():
    """Server falls through to HMAC-only path when no signature header is provided."""
    # Device has no public key — HMAC-only path, no _get_device() call for Ed25519
    device = _make_device(public_key_b64=None)
    service, mock_conn = _make_service(device)

    # No payload_signature header provided
    with patch.object(service, "_verify_hmac", return_value=True):
        mock_conn.fetchrow = AsyncMock(return_value={"transaction_id": "txn-001"})

        result = await service.sync_transactions(
            device_id="test-device-001",
            transactions=SAMPLE_TRANSACTIONS,
            api_key="test-api-key",
            # payload_signature not provided → HMAC-only path
        )

    # Should not be rejected for Ed25519 reasons
    assert not any(
        "Ed25519" in r.get("reason", "") or "X-Payload-Signature" in r.get("reason", "")
        for r in result["rejected"]
    )
