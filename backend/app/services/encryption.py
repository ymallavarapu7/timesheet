"""
AES-256-GCM encryption for sensitive mailbox credentials.
Key is loaded from settings.encryption_key (32-byte hex string).
"""

import base64
import os

from app.core.config import settings


def _get_key() -> bytes:
    """Derive a 32-byte AES key from the configured hex string."""
    key_hex = settings.encryption_key.strip()
    if not key_hex:
        raise ValueError(
            "ENCRYPTION_KEY is not set. Generate one with: "
            "python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    try:
        key = bytes.fromhex(key_hex)
    except ValueError as exc:
        raise ValueError("ENCRYPTION_KEY must be a valid hex string.") from exc

    if len(key) != 32:
        raise ValueError("ENCRYPTION_KEY must decode to exactly 32 bytes.")

    return key


def _get_aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "cryptography is required for mailbox credential encryption."
        ) from exc
    return AESGCM


def encrypt(plaintext: str) -> str:
    """
    Encrypt a UTF-8 string using AES-256-GCM.

    Returns a base64-encoded string containing the nonce followed by the
    ciphertext payload.
    """
    nonce = os.urandom(12)
    aesgcm = _get_aesgcm()(_get_key())
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt(encrypted: str) -> str:
    """Decrypt a base64-encoded AES-256-GCM value."""
    try:
        combined = base64.b64decode(encrypted.encode("utf-8"))
        nonce = combined[:12]
        ciphertext = combined[12:]
        plaintext = _get_aesgcm()(_get_key()).decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    except Exception as exc:
        raise ValueError(f"Decryption failed: {exc}") from exc
