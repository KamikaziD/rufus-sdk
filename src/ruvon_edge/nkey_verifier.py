"""
nkey_verifier.py — Ed25519 signature verification for WASM patch broadcasts.

The ``ruvon.node.patch`` NATS subject delivers compiled WASM binaries to the
entire fleet.  Without signature verification, any node on the NATS network
can push arbitrary WASM and have it hot-swapped into running devices.

``NKeyPatchVerifier`` validates an Ed25519 signature produced by the Tier 2+
build node (or control plane) that compiled and signed the binary before
broadcasting it.  It uses the ``cryptography`` package which is already a
declared dependency (``cryptography >= 41.0`` in pyproject.toml).

Usage::

    verifier = NKeyPatchVerifier.from_env()   # reads RUVON_NKEY_PUBLIC_KEY
    if verifier and not verifier.verify(binary, signature_b64):
        logger.warning("Patch rejected: bad signature")
        return

Key format
----------
The public key is expected as a URL-safe base64-encoded raw 32-byte Ed25519
public key.  Generate a keypair with::

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    print("Public:", base64.urlsafe_b64encode(pub_bytes).decode())
    # Sign a binary:
    sig_bytes = priv.sign(binary)
    print("Sig:", base64.urlsafe_b64encode(sig_bytes).decode())
"""

import base64
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class NKeyPatchVerifier:
    """Verify Ed25519 signatures on WASM patch binaries.

    Args:
        public_key_b64: URL-safe base64-encoded raw 32-byte Ed25519 public key.
                        Standard base64 (with ``+``/``/``) is also accepted.

    Raises:
        ValueError: If the key bytes cannot be loaded as an Ed25519 public key.
    """

    def __init__(self, public_key_b64: str) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        # Accept both URL-safe and standard base64
        try:
            key_bytes = base64.urlsafe_b64decode(
                public_key_b64 + "=" * (-len(public_key_b64) % 4)
            )
        except Exception:
            key_bytes = base64.b64decode(
                public_key_b64 + "=" * (-len(public_key_b64) % 4)
            )

        if len(key_bytes) != 32:
            raise ValueError(
                f"Ed25519 public key must be 32 bytes, got {len(key_bytes)}"
            )

        self._public_key: Ed25519PublicKey = Ed25519PublicKey.from_public_bytes(key_bytes)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(self, binary: bytes, signature_b64: str) -> bool:
        """Return True if ``signature_b64`` is a valid Ed25519 signature over ``binary``.

        Args:
            binary:        The raw WASM binary bytes.
            signature_b64: URL-safe or standard base64-encoded 64-byte signature.

        Returns:
            True  — signature is cryptographically valid.
            False — signature is invalid, malformed, or empty.
        """
        from cryptography.exceptions import InvalidSignature

        if not signature_b64:
            logger.debug("[NKey] Empty signature — verification failed")
            return False

        try:
            sig_bytes = base64.urlsafe_b64decode(
                signature_b64 + "=" * (-len(signature_b64) % 4)
            )
        except Exception:
            try:
                sig_bytes = base64.b64decode(
                    signature_b64 + "=" * (-len(signature_b64) % 4)
                )
            except Exception as e:
                logger.debug("[NKey] Cannot decode signature: %s", e)
                return False

        try:
            self._public_key.verify(sig_bytes, binary)
            return True
        except InvalidSignature:
            return False
        except Exception as e:
            logger.debug("[NKey] Unexpected verification error: %s", e)
            return False

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> Optional["NKeyPatchVerifier"]:
        """Create a verifier from the ``RUVON_NKEY_PUBLIC_KEY`` environment variable.

        Returns:
            A configured ``NKeyPatchVerifier`` if the variable is set and valid.
            ``None`` if the variable is absent (verification will be skipped).

        Logs a warning if the variable is set but the key cannot be parsed.
        """
        raw = os.getenv("RUVON_NKEY_PUBLIC_KEY", "").strip()
        if not raw:
            return None
        try:
            return cls(raw)
        except Exception as e:
            logger.warning(
                "[NKey] RUVON_NKEY_PUBLIC_KEY is set but could not be loaded: %s — "
                "patch signature verification will be DISABLED", e
            )
            return None
