import os
import base64
import logging
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_cipher_suite = None

def _get_cipher_suite():
    global _cipher_suite
    if _cipher_suite:
        return _cipher_suite

    key = os.getenv("RUFUS_ENCRYPTION_KEY")
    if not key:
        logger.warning("RUFUS_ENCRYPTION_KEY not set. Generating a temporary key for this session.")
        # This is strictly for dev/testing. Data won't persist across restarts if key changes.
        key = Fernet.generate_key()
    elif isinstance(key, str):
        key = key.encode()

    try:
        _cipher_suite = Fernet(key)
    except Exception as e:
        logger.error(f"Invalid RUFUS_ENCRYPTION_KEY: {e}")
        raise

    return _cipher_suite

def encrypt_string(data: str) -> bytes:
    """Encrypts a string into bytes."""
    if data is None:
        return None
    cipher = _get_cipher_suite()
    return cipher.encrypt(data.encode('utf-8'))

def decrypt_string(data: bytes) -> str:
    """Decrypts bytes into a string."""
    if data is None:
        return None
    cipher = _get_cipher_suite()
    return cipher.decrypt(data).decode('utf-8')
