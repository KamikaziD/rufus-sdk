"""NKey/Ed25519 patch verifier for WASM binary integrity.

Verifies that incoming WASM patch broadcasts were signed by a trusted operator
key using NATS NKeys (Ed25519 Ed25519 public-key primitives).

Trust chain::

    Operator Root Seed
        └── Account Key
                └── Scoped Evolution JWT (signing key for patch messages)

Each patch message carries:
  - ``wasm_hash``: SHA-256 hex of the binary
  - ``binary_b64``: base64-encoded .wasm bytes
  - ``sig``: base64url-encoded Ed25519 signature over SHA-256(binary)

Usage::

    verifier = NKeyPatchVerifier(trusted_public_key="AABCDE...")
    ok = verifier.verify(binary, sig_b64)
    if not ok:
        # discard patch

Graceful fallback: if the ``nkeys`` package is not installed the verifier logs
a warning and returns True (no-op), allowing deployments without NKey infra to
keep working.  Production deployments should install ``nkeys`` and configure a
trusted public key via the ``RUVON_PATCH_PUBLIC_KEY`` environment variable.

Install nkeys::

    pip install nkeys           # pure-Python ed25519 via the NATS nkeys library
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Sentinel: nkeys is not installed
_NKEYS_AVAILABLE: Optional[bool] = None


def _check_nkeys() -> bool:
    global _NKEYS_AVAILABLE
    if _NKEYS_AVAILABLE is None:
        try:
            import nkeys  # noqa: F401
            _NKEYS_AVAILABLE = True
        except ImportError:
            _NKEYS_AVAILABLE = False
            logger.warning(
                "nkeys package not installed — NKey signature verification disabled. "
                "Install it with: pip install nkeys"
            )
    return _NKEYS_AVAILABLE


class NKeyPatchVerifier:
    """Verify Ed25519-signed WASM patch messages using NATS NKeys.

    Args:
        trusted_public_key: Base32-encoded NKey public key (starts with ``A``
                            for account keys or ``U`` for user keys).
                            Defaults to ``RUVON_PATCH_PUBLIC_KEY`` env var.

    If neither the constructor argument nor the env var is set, the verifier
    runs in no-op mode (all patches accepted with a warning).
    """

    def __init__(self, trusted_public_key: Optional[str] = None) -> None:
        self._public_key: Optional[str] = (
            trusted_public_key or os.getenv("RUVON_PATCH_PUBLIC_KEY")
        )
        if not self._public_key:
            logger.warning(
                "NKeyPatchVerifier: no trusted_public_key configured — "
                "running in no-op mode (all patches accepted). "
                "Set RUVON_PATCH_PUBLIC_KEY to enable signature verification."
            )

    def verify(self, binary: bytes, sig_b64: str) -> bool:
        """Return True if the signature over SHA-256(binary) is valid.

        Args:
            binary:  Raw .wasm bytes received in the patch broadcast.
            sig_b64: Base64url-encoded Ed25519 signature from the patch message.

        Returns:
            True if the signature is valid (or if nkeys/public-key is not
            configured), False if the signature is present but invalid.
        """
        # No-op mode: accept everything
        if not self._public_key:
            return True

        if not sig_b64:
            logger.warning("NKeyPatchVerifier: no signature in patch message — rejecting")
            return False

        if not _check_nkeys():
            # nkeys not installed — log and accept (fail open for compatibility)
            logger.warning(
                "NKeyPatchVerifier: nkeys not installed, cannot verify signature — accepting"
            )
            return True

        try:
            import nkeys

            # The signed payload is the raw SHA-256 digest (32 bytes)
            digest = hashlib.sha256(binary).digest()

            # Decode signature from base64url
            padding = 4 - len(sig_b64) % 4
            if padding != 4:
                sig_b64 += "=" * padding
            sig_bytes = base64.urlsafe_b64decode(sig_b64)

            # Create a Keys object from the public key and verify
            kp = nkeys.from_public_key(self._public_key.encode())
            kp.verify(digest, sig_bytes)
            return True

        except Exception as exc:
            logger.warning("NKeyPatchVerifier: signature verification failed — %s", exc)
            return False
