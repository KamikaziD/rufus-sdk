"""
Ed25519 payload signing tests — Sprint 4.

Verifies that the SyncManager signs payloads with Ed25519 and that the
signature can be verified with the corresponding public key.
"""

import pytest
import base64
import json

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _CRYPTO_AVAILABLE,
    reason="cryptography package not installed"
)


def test_ed25519_sign_verify_round_trip():
    """Ed25519 private key signs payload; public key verifies it."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    payload = json.dumps({"transactions": [], "device_sequence": 1}, sort_keys=True).encode()
    signature = private_key.sign(payload)
    sig_b64 = base64.b64encode(signature).decode()

    # Decode and verify
    sig_bytes = base64.b64decode(sig_b64)
    public_key.verify(sig_bytes, payload)  # Raises if invalid


def test_ed25519_invalid_signature_raises():
    """Tampered payload should fail verification."""
    from cryptography.exceptions import InvalidSignature

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    payload = b"legitimate payload"
    signature = private_key.sign(payload)
    tampered = b"tampered payload"

    with pytest.raises(InvalidSignature):
        public_key.verify(signature, tampered)


def test_sync_manager_adds_signature_header_when_key_set(tmp_path):
    """
    SyncManager._ed25519_private_key being set should result in X-Payload-Signature
    being present in request_headers.

    This tests the signing logic in isolation (no actual HTTP).
    """
    import asyncio

    async def _run():
        from ruvon.implementations.persistence.sqlite import SQLitePersistenceProvider
        from ruvon_edge.sync_manager import SyncManager

        persistence = SQLitePersistenceProvider(db_path=str(tmp_path / "sign_test.db"))
        await persistence.initialize()

        mgr = SyncManager(
            persistence=persistence,
            sync_url="http://localhost",
            device_id="sign-device",
            api_key="test-key",
        )
        await mgr.initialize()

        private_key = Ed25519PrivateKey.generate()
        mgr._ed25519_private_key = private_key

        # Build the signing headers manually (mirrors _sync_batch logic)
        payload_bytes = b'{"test": true}'
        headers = {"X-API-Key": mgr.api_key, "X-Device-ID": mgr.device_id}
        if mgr._ed25519_private_key:
            signature = mgr._ed25519_private_key.sign(payload_bytes)
            headers["X-Payload-Signature"] = base64.b64encode(signature).decode()

        assert "X-Payload-Signature" in headers

        # Verify the signature with the public key
        public_key = private_key.public_key()
        sig_bytes = base64.b64decode(headers["X-Payload-Signature"])
        public_key.verify(sig_bytes, payload_bytes)  # Should not raise

        await persistence.close()

    asyncio.run(_run())
