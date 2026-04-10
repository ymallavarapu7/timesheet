# Core module exports
from app.core.config import settings

try:
    from app.core.security import (
        verify_password,
        get_password_hash,
        create_access_token,
        create_refresh_token,
        decode_token,
    )
except ModuleNotFoundError:
    verify_password = None
    get_password_hash = None
    create_access_token = None
    create_refresh_token = None
    decode_token = None

__all__ = [
    "settings",
    "verify_password",
    "get_password_hash",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
]
