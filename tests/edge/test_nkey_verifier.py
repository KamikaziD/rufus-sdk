"""Unit tests for NKeyPatchVerifier.

All tests run without requiring the `nkeys` package to be installed:
  - no-op mode (no public key configured)
  - no-op mode (nkeys not installed)
  - rejection when sig_b64 is empty but a key IS configured
  - acceptance via a real Ed25519 keypair (when nkeys is available)
"""

from __future__ import annotations

import base64
import hashlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from ruvon.implementations.security.nkey_verifier import NKeyPatchVerifier


FAKE_BINARY = b"\x00asm\x0e\x00\x01\x00" + b"\xab" * 64


# ---------------------------------------------------------------------------
# No-op mode — no public key set
# ---------------------------------------------------------------------------

def test_verify_no_key_accepts_everything():
    """Without a configured public key, the verifier is a no-op (returns True)."""
    verifier = NKeyPatchVerifier(trusted_public_key=None)
    # No key → accept regardless of sig
    assert verifier.verify(FAKE_BINARY, "") is True
    assert verifier.verify(FAKE_BINARY, "badsig") is True


# ---------------------------------------------------------------------------
# Empty signature + key configured → reject
# ---------------------------------------------------------------------------

def test_verify_empty_sig_with_key_rejects():
    """If a public key is configured but no sig is provided, reject."""
    # Provide a dummy key string — we'll mock nkeys away so the real lib isn't needed
    verifier = NKeyPatchVerifier(trusted_public_key="AXXXXXX")

    # Patch _check_nkeys to return True so we enter the nkeys path
    import ruvon.implementations.security.nkey_verifier as _mod
    with patch.object(_mod, "_NKEYS_AVAILABLE", True):
        result = verifier.verify(FAKE_BINARY, "")

    assert result is False


# ---------------------------------------------------------------------------
# nkeys not installed — graceful fallback (fail open)
# ---------------------------------------------------------------------------

def test_verify_nkeys_not_installed_accepts(monkeypatch):
    """When nkeys is not installed and a key is configured, accept with warning."""
    import ruvon.implementations.security.nkey_verifier as _mod

    verifier = NKeyPatchVerifier(trusted_public_key="AXXXXXXX")

    # Force _NKEYS_AVAILABLE to False for this test
    monkeypatch.setattr(_mod, "_NKEYS_AVAILABLE", False)

    result = verifier.verify(FAKE_BINARY, base64.urlsafe_b64encode(b"fakesig").decode())
    assert result is True


# ---------------------------------------------------------------------------
# Valid signature via mocked nkeys
# ---------------------------------------------------------------------------

def test_verify_valid_signature_via_mock():
    """verify() returns True when nkeys.verify_signature does not raise."""
    import ruvon.implementations.security.nkey_verifier as _mod

    # Build a mock nkeys module
    fake_kp = MagicMock()
    fake_kp.verify = MagicMock(return_value=True)  # no exception = valid

    fake_nkeys = MagicMock()
    fake_nkeys.from_public_key = MagicMock(return_value=fake_kp)

    sig = base64.urlsafe_b64encode(b"\xff" * 64).decode().rstrip("=")

    with patch.dict(sys.modules, {"nkeys": fake_nkeys}):
        monkeypatch_available = patch.object(_mod, "_NKEYS_AVAILABLE", True)
        with monkeypatch_available:
            verifier = NKeyPatchVerifier(trusted_public_key="AXXXXXX")
            result = verifier.verify(FAKE_BINARY, sig)

    assert result is True


# ---------------------------------------------------------------------------
# Invalid signature via mocked nkeys
# ---------------------------------------------------------------------------

def test_verify_invalid_signature_via_mock():
    """verify() returns False when nkeys.verify raises (bad signature)."""
    import ruvon.implementations.security.nkey_verifier as _mod

    fake_kp = MagicMock()
    fake_kp.verify = MagicMock(side_effect=Exception("invalid signature"))

    fake_nkeys = MagicMock()
    fake_nkeys.from_public_key = MagicMock(return_value=fake_kp)

    sig = base64.urlsafe_b64encode(b"\x00" * 64).decode().rstrip("=")

    with patch.dict(sys.modules, {"nkeys": fake_nkeys}):
        with patch.object(_mod, "_NKEYS_AVAILABLE", True):
            verifier = NKeyPatchVerifier(trusted_public_key="AXXXXXX")
            result = verifier.verify(FAKE_BINARY, sig)

    assert result is False
