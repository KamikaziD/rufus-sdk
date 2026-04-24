"""
nkey_signer.py — Ed25519 signing for WASM patches and EchoForge gossip payloads.

Complements ``NKeyPatchVerifier`` in nkey_verifier.py.  Where the verifier
holds a public key and checks incoming signatures, this signer holds the
private key and produces them.

Usage::

    # One-time keypair generation (run once, store keys securely)
    signer, pub_b64 = NKeyPatchSigner.generate_keypair()
    print("Set RUFUS_NKEY_PRIVATE_KEY =", signer._private_key_b64)
    print("Set RUFUS_NKEY_PUBLIC_KEY  =", pub_b64)

    # Runtime signing (Tier 2+ build/forge nodes)
    signer = NKeyPatchSigner.from_env()   # reads RUFUS_NKEY_PRIVATE_KEY
    if signer:
        sig_b64 = signer.sign(binary)

Key format
----------
Private key: URL-safe base64-encoded raw 32-byte Ed25519 seed.
Public key:  URL-safe base64-encoded raw 32-byte Ed25519 public key.

Both use the same encoding as ``NKeyPatchVerifier`` so they interoperate
directly — ``signer.sign(b)`` produces a signature that
``NKeyPatchVerifier(pub_b64).verify(b, sig_b64)`` accepts.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_ENV_VAR = "RUFUS_NKEY_PRIVATE_KEY"


class NKeyPatchSigner:
    """Ed25519 signer for WASM patch binaries and EchoForge gossip payloads.

    Args:
        private_key_b64: URL-safe (or standard) base64-encoded raw 32-byte
                         Ed25519 private key seed.

    Raises:
        ValueError: If the decoded bytes are not a valid 32-byte Ed25519 seed.
    """

    def __init__(self, private_key_b64: str) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        try:
            seed = base64.urlsafe_b64decode(
                private_key_b64 + "=" * (-len(private_key_b64) % 4)
            )
        except Exception:
            seed = base64.b64decode(
                private_key_b64 + "=" * (-len(private_key_b64) % 4)
            )

        if len(seed) != 32:
            raise ValueError(
                f"Ed25519 private key seed must be 32 bytes, got {len(seed)}"
            )

        self._private_key: Ed25519PrivateKey = Ed25519PrivateKey.from_private_bytes(seed)
        # Cache for generate_keypair() to return the encoded form
        self._private_key_b64: str = base64.urlsafe_b64encode(seed).decode().rstrip("=")

    # ------------------------------------------------------------------
    # Core signing
    # ------------------------------------------------------------------

    def sign(self, data: bytes) -> str:
        """Sign ``data`` with the Ed25519 private key.

        Args:
            data: Raw bytes to sign (WASM binary, gossip payload, etc.).

        Returns:
            URL-safe base64-encoded 64-byte Ed25519 signature (no padding).
        """
        sig_bytes = self._private_key.sign(data)
        return base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")

    def public_key_b64(self) -> str:
        """Return the corresponding public key as URL-safe base64 (no padding).

        This is the value to set as ``RUFUS_NKEY_PUBLIC_KEY`` for all fleet
        nodes that need to verify signatures produced by this signer.
        """
        pub_bytes = self._private_key.public_key().public_bytes_raw()
        return base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> Optional["NKeyPatchSigner"]:
        """Create a signer from the ``RUFUS_NKEY_PRIVATE_KEY`` environment variable.

        Returns:
            A configured ``NKeyPatchSigner`` if the variable is set and valid.
            ``None`` if the variable is absent (signing will be skipped — the
            patch broadcast will include an empty ``signature_b64``).

        Logs a warning if the variable is set but the key cannot be parsed.
        """
        raw = os.getenv(_ENV_VAR, "").strip()
        if not raw:
            return None
        try:
            return cls(raw)
        except Exception as e:
            logger.warning(
                "[NKeySigner] %s is set but could not be loaded: %s — "
                "patch signing will be DISABLED", _ENV_VAR, e
            )
            return None

    @staticmethod
    def generate_keypair() -> Tuple["NKeyPatchSigner", str]:
        """Generate a fresh Ed25519 keypair.

        Returns:
            ``(signer, public_key_b64)`` — the signer holds the private key;
            ``public_key_b64`` is the value to distribute to fleet nodes as
            ``RUFUS_NKEY_PUBLIC_KEY``.

        Example::

            signer, pub_b64 = NKeyPatchSigner.generate_keypair()
            # Store signer._private_key_b64 as RUFUS_NKEY_PRIVATE_KEY (secret)
            # Distribute pub_b64 as RUFUS_NKEY_PUBLIC_KEY (public)
        """
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        priv = Ed25519PrivateKey.generate()
        seed = priv.private_bytes_raw()
        priv_b64 = base64.urlsafe_b64encode(seed).decode().rstrip("=")
        signer = NKeyPatchSigner(priv_b64)
        return signer, signer.public_key_b64()
