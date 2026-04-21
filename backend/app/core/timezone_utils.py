"""
Tenant timezone helpers.

Resolve an IANA timezone string from ``Tenant.timezone`` (added in migration
029) to a ``tzinfo`` object, and provide tenant-aware ``now`` / ``today`` /
``combine`` helpers for scheduling and deadline calculations.

Contract: every helper accepts ``Optional[str]`` and falls back to UTC when
the string is ``None``, empty, or unrecognized. An unrecognized string logs a
warning so operators notice misconfiguration but doesn't crash the request.
"""
from datetime import datetime, date, time as _time
from datetime import timezone as _stdlib_tz
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional, Union
import logging

logger = logging.getLogger(__name__)
UTC = _stdlib_tz.utc


def resolve_tz(tenant_timezone: Optional[str]) -> Union[ZoneInfo, _stdlib_tz]:
    """
    Return a tzinfo for the given IANA timezone string.
    Falls back to UTC if the string is None, empty, or unrecognized.
    Logs a warning on unrecognized strings so operators notice misconfiguration.
    """
    if not tenant_timezone:
        return UTC
    try:
        return ZoneInfo(tenant_timezone)
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning(
            "tenant_timezone: unrecognized IANA timezone %r, falling back to UTC",
            tenant_timezone,
        )
        return UTC


def now_for_tenant(tenant_timezone: Optional[str]) -> datetime:
    """Current datetime in the tenant's timezone."""
    return datetime.now(resolve_tz(tenant_timezone))


def today_for_tenant(tenant_timezone: Optional[str]) -> date:
    """Current date in the tenant's timezone."""
    return now_for_tenant(tenant_timezone).date()


def combine_tenant(
    d: date,
    t: _time,
    tenant_timezone: Optional[str],
) -> datetime:
    """
    Combine a date and time in the tenant's timezone and return a
    timezone-aware datetime. Used for deadline calculations.
    """
    tz = resolve_tz(tenant_timezone)
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=tz)
