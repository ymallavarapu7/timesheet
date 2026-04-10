import bcrypt
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from app.core.config import settings

logger = logging.getLogger(__name__)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(
            timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode.update({"exp": int(expire.timestamp())})
    encoded_jwt = jwt.encode(
        to_encode, settings.secret_key, algorithm=settings.algorithm)
    logger.debug("Token created successfully")
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> tuple[str, str, datetime]:
    """Create a JWT refresh token with a unique jti claim.

    Returns (encoded_jwt, jti, expires_at) so the caller can persist the token.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + \
            timedelta(days=settings.refresh_token_expire_days)

    jti = secrets.token_urlsafe(32)
    to_encode.update({"exp": int(expire.timestamp()), "jti": jti})
    encoded_jwt = jwt.encode(
        to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt, jti, expire


def generate_service_token() -> str:
    """
    Generate a cryptographically secure random service token.
    Returns the plaintext token — store this securely in the ingestion platform.
    The timesheet app only stores the bcrypt hash.
    """
    return secrets.token_urlsafe(48)  # 64-character URL-safe string


def hash_service_token(token: str) -> str:
    """Hash a service token for storage. Uses bcrypt."""
    return bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode()


def verify_service_token(plain_token: str, hashed_token: str) -> bool:
    """Verify a plaintext token against its stored hash."""
    return bcrypt.checkpw(plain_token.encode(), hashed_token.encode())


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, settings.secret_key,
                             algorithms=[settings.algorithm])
        logger.debug("Token decoded successfully")
        return payload
    except JWTError as e:
        logger.error(
            f"JWT decode error: {e}")
        return None
