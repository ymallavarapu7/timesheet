"""
AES-256-GCM encryption for sensitive mailbox credentials.

Format
------
New ciphertexts are written with an explicit version prefix:

    v1.<base64(nonce(12) || ciphertext)>

Legacy ciphertexts (no prefix) are pure base64 of nonce||ciphertext.
``decrypt()`` accepts both formats so existing rows keep working without
a data migration.

Key rotation
------------
``settings.encryption_key`` is the *active* key, used for all new encryption.
``settings.encryption_keys_legacy`` (optional, comma-separated hex keys)
is the list of previously-active keys, used only for decryption fallback.

Rotation procedure (operator action, not an automatic migration):
  1. Append the current ``ENCRYPTION_KEY`` to ``ENCRYPTION_KEYS_LEGACY``.
  2. Set a fresh ``ENCRYPTION_KEY`` (32-byte hex).
  3. Restart the api / worker. From this point new tokens use the new
     key; old tokens still decrypt via the legacy list.
  4. Optionally re-encrypt existing rows in place over time. Once every
     row has been re-encrypted under the new key, the legacy entry can
     be removed from ``ENCRYPTION_KEYS_LEGACY``.
"""

import base64
import os

from app.core.config import settings


_VERSION_PREFIX_V1 = "v1."


def _key_from_hex(key_hex: str) -> bytes:
    key_hex = key_hex.strip()
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


def _get_active_key() -> bytes:
    """The key used for all new encryption."""
    return _key_from_hex(settings.encryption_key)


def _get_decrypt_keys() -> list[bytes]:
    """All keys eligible for decryption: active first, then legacy keys.

    Trying the active key first means the common case (no rotation in
    flight) is fast, and rotated-but-not-yet-re-encrypted rows succeed
    on the second-or-later attempt without a fast-path penalty.
    """
    keys = [_get_active_key()]
    legacy = getattr(settings, "encryption_keys_legacy", None) or ""
    if isinstance(legacy, str) and legacy.strip():
        for entry in legacy.split(","):
            entry = entry.strip()
            if not entry:
                continue
            try:
                keys.append(_key_from_hex(entry))
            except ValueError:
                # A malformed legacy key shouldn't kill decryption of
                # rows protected by the active or other legacy keys. Skip
                # it; if no key works, the caller still gets a clear
                # "Decryption failed" error.
                continue
    return keys


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
    Encrypt a UTF-8 string using AES-256-GCM under the active key.

    Returns a versioned string of the form ``v1.<base64(nonce||ciphertext)>``.
    """
    nonce = os.urandom(12)
    aesgcm = _get_aesgcm()(_get_active_key())
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    body = base64.b64encode(nonce + ciphertext).decode("utf-8")
    return f"{_VERSION_PREFIX_V1}{body}"


def decrypt(encrypted: str) -> str:
    """Decrypt a value produced by :func:`encrypt`.

    Accepts both the v1 prefix format and the legacy format (pure
    base64) so rows written before key versioning was introduced keep
    working without a data migration.
    """
    AESGCM = _get_aesgcm()
    if encrypted.startswith(_VERSION_PREFIX_V1):
        body = encrypted[len(_VERSION_PREFIX_V1):]
    else:
        body = encrypted

    try:
        combined = base64.b64decode(body.encode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Decryption failed: malformed input ({exc})") from exc

    if len(combined) < 13:
        raise ValueError("Decryption failed: ciphertext too short.")

    nonce = combined[:12]
    ciphertext = combined[12:]

    last_exc: Exception | None = None
    for key in _get_decrypt_keys():
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception as exc:
            last_exc = exc
            continue

    raise ValueError(f"Decryption failed: no key could decrypt this value ({last_exc}).")
