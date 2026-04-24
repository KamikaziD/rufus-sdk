"""Unit tests for NKeyPatchSigner.

Covers:
  - generate_keypair() produces a working signer + verifiable public key
  - sign() + NKeyPatchVerifier.verify() round-trip (the core interop guarantee)
  - Tampered binary fails verification
  - from_env() returns None when env var is absent
  - from_env() returns a working signer when RUFUS_NKEY_PRIVATE_KEY is set
  - from_env() logs a warning and returns None for a malformed key
  - sign() output is URL-safe base64 with correct length (64 bytes → 86 b64 chars)
  - public_key_b64() output matches the public key returned by generate_keypair()
"""

from __future__ import annotations

import base64

import pytest

from rufus_edge.nkey_signer import NKeyPatchSigner
from rufus_edge.nkey_verifier import NKeyPatchVerifier


_SAMPLE_BINARY = b"\x00asm\x01\x00\x00\x00" + b"\xab" * 128


# ---------------------------------------------------------------------------
# Keypair generation
# ---------------------------------------------------------------------------

def test_generate_keypair_returns_signer_and_pub_key():
    signer, pub_b64 = NKeyPatchSigner.generate_keypair()
    assert isinstance(signer, NKeyPatchSigner)
    # URL-safe b64 of 32 bytes = 43 chars (no padding)
    decoded = base64.urlsafe_b64decode(pub_b64 + "=" * (-len(pub_b64) % 4))
    assert len(decoded) == 32


def test_public_key_b64_matches_generate_keypair():
    signer, pub_b64 = NKeyPatchSigner.generate_keypair()
    assert signer.public_key_b64() == pub_b64


# ---------------------------------------------------------------------------
# Sign + verify round-trip
# ---------------------------------------------------------------------------

def test_sign_verify_roundtrip():
    """sign() + NKeyPatchVerifier.verify() must return True for the same binary."""
    signer, pub_b64 = NKeyPatchSigner.generate_keypair()
    verifier = NKeyPatchVerifier(pub_b64)

    sig = signer.sign(_SAMPLE_BINARY)
    assert verifier.verify(_SAMPLE_BINARY, sig) is True


def test_sign_verify_roundtrip_small_binary():
    signer, pub_b64 = NKeyPatchSigner.generate_keypair()
    verifier = NKeyPatchVerifier(pub_b64)
    binary = b"hello"
    sig = signer.sign(binary)
    assert verifier.verify(binary, sig) is True


def test_tampered_binary_fails_verification():
    signer, pub_b64 = NKeyPatchSigner.generate_keypair()
    verifier = NKeyPatchVerifier(pub_b64)

    sig = signer.sign(_SAMPLE_BINARY)
    tampered = _SAMPLE_BINARY[:-1] + b"\xff"
    assert verifier.verify(tampered, sig) is False


def test_wrong_key_fails_verification():
    signer, _ = NKeyPatchSigner.generate_keypair()
    _, other_pub_b64 = NKeyPatchSigner.generate_keypair()
    verifier = NKeyPatchVerifier(other_pub_b64)

    sig = signer.sign(_SAMPLE_BINARY)
    assert verifier.verify(_SAMPLE_BINARY, sig) is False


# ---------------------------------------------------------------------------
# Signature format
# ---------------------------------------------------------------------------

def test_sign_produces_url_safe_base64():
    signer, _ = NKeyPatchSigner.generate_keypair()
    sig = signer.sign(_SAMPLE_BINARY)
    # Must not contain standard base64 chars '+' or '/'
    assert "+" not in sig
    assert "/" not in sig
    # Ed25519 signature is 64 bytes → 86 base64 chars (no padding)
    decoded = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
    assert len(decoded) == 64


# ---------------------------------------------------------------------------
# from_env() — absent key
# ---------------------------------------------------------------------------

def test_from_env_absent_returns_none(monkeypatch):
    monkeypatch.delenv("RUFUS_NKEY_PRIVATE_KEY", raising=False)
    assert NKeyPatchSigner.from_env() is None


# ---------------------------------------------------------------------------
# from_env() — valid key present
# ---------------------------------------------------------------------------

def test_from_env_valid_key(monkeypatch):
    signer_ref, pub_b64 = NKeyPatchSigner.generate_keypair()
    monkeypatch.setenv("RUFUS_NKEY_PRIVATE_KEY", signer_ref._private_key_b64)

    signer = NKeyPatchSigner.from_env()
    assert signer is not None

    # The loaded signer must produce a signature that the paired verifier accepts
    verifier = NKeyPatchVerifier(pub_b64)
    sig = signer.sign(_SAMPLE_BINARY)
    assert verifier.verify(_SAMPLE_BINARY, sig) is True


# ---------------------------------------------------------------------------
# from_env() — malformed key
# ---------------------------------------------------------------------------

def test_from_env_malformed_key_returns_none(monkeypatch, caplog):
    monkeypatch.setenv("RUFUS_NKEY_PRIVATE_KEY", "not-a-valid-key!!!")
    import logging
    with caplog.at_level(logging.WARNING, logger="rufus_edge.nkey_signer"):
        result = NKeyPatchSigner.from_env()
    assert result is None
    assert "could not be loaded" in caplog.text


# ---------------------------------------------------------------------------
# Constructor — wrong key length
# ---------------------------------------------------------------------------

def test_constructor_wrong_length_raises():
    # 16 bytes → should raise ValueError
    short_key = base64.urlsafe_b64encode(b"\x00" * 16).decode()
    with pytest.raises(ValueError, match="32 bytes"):
        NKeyPatchSigner(short_key)


# ---------------------------------------------------------------------------
# Determinism: same key + same data → same signature
# ---------------------------------------------------------------------------

def test_sign_is_deterministic():
    signer, _ = NKeyPatchSigner.generate_keypair()
    sig1 = signer.sign(_SAMPLE_BINARY)
    sig2 = signer.sign(_SAMPLE_BINARY)
    assert sig1 == sig2
