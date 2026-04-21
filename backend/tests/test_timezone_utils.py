"""
Tests for ``app.core.timezone_utils``.

These are pure-function tests — no DB. Cover the four helpers:
``resolve_tz``, ``now_for_tenant``, ``today_for_tenant``, ``combine_tenant``.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from datetime import timezone as stdlib_tz
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.core.timezone_utils import (
    UTC,
    combine_tenant,
    now_for_tenant,
    resolve_tz,
    today_for_tenant,
)


def test_resolve_tz_returns_utc_for_none():
    assert resolve_tz(None) is UTC


def test_resolve_tz_returns_utc_for_empty_string():
    assert resolve_tz("") is UTC


def test_resolve_tz_returns_correct_zone_for_valid_iana_name():
    resolved = resolve_tz("America/New_York")
    assert isinstance(resolved, ZoneInfo)
    assert str(resolved) == "America/New_York"


def test_resolve_tz_falls_back_to_utc_for_invalid_name(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="app.core.timezone_utils"):
        result = resolve_tz("Not/AZone")
    assert result is UTC
    # Confirm the warning actually fired so operators see misconfiguration.
    assert any("unrecognized IANA timezone" in rec.message for rec in caplog.records)


def test_now_for_tenant_returns_aware_datetime():
    result = now_for_tenant("America/New_York")
    assert result.tzinfo is not None
    assert str(result.tzinfo) == "America/New_York"


def test_now_for_tenant_with_none_returns_utc_aware():
    result = now_for_tenant(None)
    assert result.tzinfo is not None
    # UTC offset is zero regardless of the exact object identity.
    assert result.utcoffset().total_seconds() == 0


def test_today_for_tenant_returns_correct_date_for_timezone():
    """
    Freeze a moment that is 'yesterday' in UTC but 'today' in Asia/Tokyo.
    Confirms ``today_for_tenant`` returns the *tenant's* date, not the
    server-local date.

    2026-04-20 22:00 UTC  →  2026-04-21 07:00 JST.
    today_for_tenant("UTC")         == 2026-04-20
    today_for_tenant("Asia/Tokyo")  == 2026-04-21
    """
    frozen_utc = datetime(2026, 4, 20, 22, 0, tzinfo=timezone.utc)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen_utc.replace(tzinfo=None)
            return frozen_utc.astimezone(tz)

    with patch("app.core.timezone_utils.datetime", _FrozenDatetime):
        assert today_for_tenant("UTC") == date(2026, 4, 20)
        assert today_for_tenant("Asia/Tokyo") == date(2026, 4, 21)


def test_combine_tenant_returns_aware_datetime_in_correct_tz():
    dt = combine_tenant(date(2026, 4, 21), time(hour=10, minute=0), "America/New_York")
    assert dt.tzinfo is not None
    assert str(dt.tzinfo) == "America/New_York"
    assert dt.year == 2026 and dt.month == 4 and dt.day == 21
    assert dt.hour == 10 and dt.minute == 0


def test_combine_tenant_with_none_returns_utc_aware():
    dt = combine_tenant(date(2026, 4, 21), time(hour=10, minute=0), None)
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0
