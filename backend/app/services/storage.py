"""
File storage abstraction.
STORAGE_PROVIDER=local -> saves to STORAGE_PATH on disk
STORAGE_PROVIDER=s3 -> saves to S3_BUCKET
"""

import asyncio
import logging
import uuid
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


# Extensions we are willing to write to disk verbatim. Everything else
# is normalized to ``.bin`` so a malicious sender can't park
# ``.php``/``.html``/``.svg`` etc. on the server's filesystem and
# attempt a content-type confusion or active-content attack later.
_ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".webp",
    ".txt",
    ".eml",
    ".msg",
    ".zip",
}


def _safe_extension(filename: str) -> str:
    """Return the file's extension only if it's in the allowlist;
    otherwise return ``.bin``. Lowercased. Empty extension also falls
    back to ``.bin`` so every key has a stable shape."""
    ext = Path(filename).suffix.lower()
    if not ext:
        return ".bin"
    return ext if ext in _ALLOWED_ATTACHMENT_EXTENSIONS else ".bin"


def _generate_key(filename: str) -> str:
    """Generate a unique storage key for an uploaded attachment.

    The on-disk filename is a fresh UUID; the original filename is
    never trusted into the filesystem path. The extension is preserved
    only when it's in the active-content-safe allowlist (see
    ``_ALLOWED_ATTACHMENT_EXTENSIONS``); anything else becomes ``.bin``.
    """
    return f"attachments/{uuid.uuid4().hex}{_safe_extension(filename)}"


async def save_file(content: bytes, filename: str) -> str:
    """Save file bytes to the configured storage backend."""
    key = _generate_key(filename)
    if settings.storage_provider.lower() == "s3":
        return await _save_s3(content, key)
    return await _save_local(content, key)


async def read_file(storage_key: str) -> bytes:
    """Read file bytes from the configured storage backend."""
    if settings.storage_provider.lower() == "s3":
        return await _read_s3(storage_key)
    return await _read_local(storage_key)


async def delete_file(storage_key: str) -> None:
    """Delete a file from the configured storage backend."""
    if settings.storage_provider.lower() == "s3":
        await _delete_s3(storage_key)
        return
    await _delete_local(storage_key)


async def _save_local(content: bytes, key: str) -> str:
    base_path = Path(settings.storage_path).resolve()
    full_path = (base_path / key).resolve()
    if not str(full_path).startswith(str(base_path)):
        raise ValueError("Invalid storage key: path traversal detected")
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(content)
    logger.debug("Saved file locally to %s", full_path)
    return key


async def _read_local(storage_key: str) -> bytes:
    base_path = Path(settings.storage_path).resolve()
    full_path = (base_path / storage_key).resolve()
    if not str(full_path).startswith(str(base_path)):
        raise ValueError("Invalid storage key: path traversal detected")
    if not full_path.exists():
        raise FileNotFoundError(f"File not found: {storage_key}")
    return full_path.read_bytes()


async def _delete_local(storage_key: str) -> None:
    base_path = Path(settings.storage_path).resolve()
    full_path = (base_path / storage_key).resolve()
    if not str(full_path).startswith(str(base_path)):
        raise ValueError("Invalid storage key: path traversal detected")
    if full_path.exists():
        full_path.unlink()


def _get_s3_client():
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "boto3 is required for S3 storage support but is not installed."
        ) from exc

    return boto3.client(
        "s3",
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )


async def _save_s3(content: bytes, key: str) -> str:
    def _upload() -> str:
        client = _get_s3_client()
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=content)
        return key

    try:
        return await asyncio.to_thread(_upload)
    except Exception as exc:
        logger.error("S3 save failed: %s", exc)
        raise


async def _read_s3(storage_key: str) -> bytes:
    def _download() -> bytes:
        client = _get_s3_client()
        response = client.get_object(Bucket=settings.s3_bucket, Key=storage_key)
        return response["Body"].read()

    try:
        return await asyncio.to_thread(_download)
    except Exception as exc:
        logger.error("S3 read failed: %s", exc)
        raise


async def _delete_s3(storage_key: str) -> None:
    def _delete() -> None:
        client = _get_s3_client()
        client.delete_object(Bucket=settings.s3_bucket, Key=storage_key)

    try:
        await asyncio.to_thread(_delete)
    except Exception as exc:
        logger.error("S3 delete failed: %s", exc)
        raise
