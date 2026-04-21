"""
Typed tenant-settings accessor.

The existing ``TenantSettings`` key/value table continues to store per-tenant
overrides as strings. This module is the single place that couples a stored
string (or a missing row) to a typed Python value by consulting the global
``setting_definitions`` catalog.

Public API
----------
``get_setting(db, tenant_id, key)``
    Read one value, typed. Falls back to the catalog default.

``set_setting(db, tenant_id, key, value, actor_id)``
    Validate, upsert, and write a ``TENANT_SETTING_CHANGED`` ActivityLog row.

``get_public_settings(db, tenant_id)``
    Every catalog key where ``is_public=True``, typed.

``get_all_settings(db, tenant_id)``
    Every catalog key, typed.

``TenantPolicy.for_tenant(db, tenant_id)``
    Convenience object that exposes the typed values as attributes for the
    most common consumers (time-entry CRUD, notifications, reminder worker).

Scope note: this PR wires the accessor into the three settings endpoints in
``app.api.users``. Other call sites that currently read ``TenantSettings``
directly (auth.py, crud/time_entry.py, crud/time_off_request.py,
workers/reminder_worker.py) keep their existing coercion and will be
migrated in a follow-up PR.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, fields
from datetime import time as _time
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog
from app.models.setting_definition import SettingDefinition
from app.models.tenant_settings import TenantSettings

logger = logging.getLogger(__name__)

# Activity type constant — kept as a module-level name so callers and tests
# can reference it without hard-coding the string in multiple places.
TENANT_SETTING_CHANGED = "TENANT_SETTING_CHANGED"

# HH:MM 24-hour, no seconds. Consistent with the existing stored values.
_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ─────────────────────────────────────────────────────────────────────────────
# Catalog loading
# ─────────────────────────────────────────────────────────────────────────────


async def _load_catalog(db: AsyncSession) -> dict[str, SettingDefinition]:
    result = await db.execute(select(SettingDefinition))
    return {row.key: row for row in result.scalars().all()}


async def _get_definition(db: AsyncSession, key: str) -> SettingDefinition:
    defn = await db.get(SettingDefinition, key)
    if defn is None:
        raise KeyError(
            f"Unknown setting key: {key!r}. Is migration 028 applied and the catalog seeded?"
        )
    return defn


async def _load_stored_values(
    db: AsyncSession, tenant_id: int, keys: Optional[set[str]] = None
) -> dict[str, Optional[str]]:
    stmt = select(TenantSettings.key, TenantSettings.value).where(
        TenantSettings.tenant_id == tenant_id
    )
    if keys is not None:
        stmt = stmt.where(TenantSettings.key.in_(keys))
    result = await db.execute(stmt)
    return {key: value for key, value in result.all()}


# ─────────────────────────────────────────────────────────────────────────────
# Coercion / validation
# ─────────────────────────────────────────────────────────────────────────────


def _coerce_stored_value(raw: Optional[str], defn: SettingDefinition) -> Any:
    """
    Convert a raw stored string (as produced by ``set_setting`` or by the
    legacy code path that just did ``str(value)``) into a typed Python value.

    Falls back to ``defn.default_value`` (JSON-parsed) when the row is
    missing or unparseable.
    """
    if raw is None:
        return _coerce_python_value(_default_as_python(defn), defn)

    dtype = defn.data_type
    # First try JSON. Values written by the new accessor are json.dumps'd so
    # booleans, ints, floats and strings all round-trip safely. Values
    # written by the legacy code path are ``str(value)`` which for most
    # scalar types is also valid JSON (``"5"``, ``"true"`` is NOT valid JSON
    # but ``True`` → ``"True"``, which we handle below).
    try:
        parsed = json.loads(raw)
        return _coerce_python_value(parsed, defn)
    except (ValueError, TypeError):
        pass

    # Legacy-style values that aren't JSON: bare words.
    if dtype == "bool":
        low = raw.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        return _default_as_python(defn)
    if dtype == "int":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return _default_as_python(defn)
    if dtype == "float":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return _default_as_python(defn)
    # string, time, json → leave as-is
    return raw


def _default_as_python(defn: SettingDefinition) -> Any:
    """``default_value`` is stored as JSONB (native) on Postgres and as a
    JSON-encoded string on SQLite (via the ``@compiles`` shim used in tests).
    Normalize both shapes."""
    value = defn.default_value
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _coerce_python_value(value: Any, defn: SettingDefinition) -> Any:
    """Nudge a Python value to the exact type declared by the catalog —
    for example, ``5`` (int) → ``5.0`` (float) when the catalog says float.
    Does not raise on mismatch; ``validate_value`` is the strict gate."""
    dtype = defn.data_type
    if value is None:
        return _default_as_python(defn)
    if dtype == "int" and isinstance(value, bool):
        return value  # bools are intish in Python; validate_value flags mismatch
    if dtype == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if dtype == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if dtype == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            low = value.strip().lower()
            if low == "true":
                return True
            if low == "false":
                return False
        return value
    return value


def validate_value(value: Any, defn: SettingDefinition) -> Any:
    """
    Strict validation. Returns the canonicalised value on success; raises
    ``ValueError`` with a human-readable message on failure. Endpoint layer
    converts those into 422 responses.
    """
    dtype = defn.data_type
    rules = defn.validation or {}

    if dtype == "int":
        # bool is a subclass of int in Python — reject explicitly.
        if isinstance(value, bool) or not isinstance(value, int):
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{defn.label}: expected an integer, got {value!r}")
        _enforce_min_max(value, rules, defn.label)
        _enforce_enum(value, rules, defn.label)
        return value

    if dtype == "float":
        if isinstance(value, bool):
            raise ValueError(f"{defn.label}: expected a number, got a boolean")
        if not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{defn.label}: expected a number, got {value!r}")
        value = float(value)
        _enforce_min_max(value, rules, defn.label)
        _enforce_enum(value, rules, defn.label)
        return value

    if dtype == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            low = value.strip().lower()
            if low == "true":
                return True
            if low == "false":
                return False
        raise ValueError(
            f"{defn.label}: expected a boolean (true/false), got {value!r}"
        )

    if dtype == "string":
        if not isinstance(value, str):
            raise ValueError(f"{defn.label}: expected a string, got {value!r}")
        if "min_length" in rules and len(value) < int(rules["min_length"]):
            raise ValueError(
                f"{defn.label}: must be at least {rules['min_length']} characters"
            )
        if "max_length" in rules and len(value) > int(rules["max_length"]):
            raise ValueError(
                f"{defn.label}: must be at most {rules['max_length']} characters"
            )
        if "enum" in rules and value not in rules["enum"]:
            raise ValueError(
                f"{defn.label}: must be one of {rules['enum']}, got {value!r}"
            )
        if "pattern" in rules and not re.match(str(rules["pattern"]), value):
            raise ValueError(f"{defn.label}: does not match required pattern")
        return value

    if dtype == "time":
        if not isinstance(value, str):
            raise ValueError(
                f"{defn.label}: expected a time string HH:MM, got {value!r}"
            )
        if not _TIME_PATTERN.match(value):
            raise ValueError(
                f"{defn.label}: must be in 24-hour HH:MM format, got {value!r}"
            )
        return value

    if dtype == "json":
        try:
            json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{defn.label}: value is not JSON-serializable") from exc
        return value

    raise ValueError(f"{defn.label}: unsupported data_type {dtype!r}")


def _enforce_min_max(value: float, rules: dict, label: str) -> None:
    if "min" in rules and value < rules["min"]:
        raise ValueError(f"{label}: must be >= {rules['min']}, got {value}")
    if "max" in rules and value > rules["max"]:
        raise ValueError(f"{label}: must be <= {rules['max']}, got {value}")


def _enforce_enum(value: Any, rules: dict, label: str) -> None:
    if "enum" in rules and value not in rules["enum"]:
        raise ValueError(f"{label}: must be one of {rules['enum']}, got {value}")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


async def get_setting(db: AsyncSession, tenant_id: int, key: str) -> Any:
    """Read one setting, typed. Falls back to the catalog default."""
    defn = await _get_definition(db, key)
    row = await db.execute(
        select(TenantSettings.value).where(
            TenantSettings.tenant_id == tenant_id,
            TenantSettings.key == key,
        )
    )
    raw = row.scalar_one_or_none()
    return _coerce_stored_value(raw, defn)


async def set_setting(
    db: AsyncSession,
    tenant_id: int,
    key: str,
    value: Any,
    actor_id: int,
) -> Any:
    """
    Validate and upsert a setting. Writes a ``TENANT_SETTING_CHANGED``
    ActivityLog row with before/after values. Returns the canonicalised
    value that was stored.

    Caller is responsible for ``await db.commit()`` — we only flush.
    """
    defn = await _get_definition(db, key)
    new_value = validate_value(value, defn)

    existing = await db.execute(
        select(TenantSettings).where(
            TenantSettings.tenant_id == tenant_id,
            TenantSettings.key == key,
        )
    )
    existing_row = existing.scalar_one_or_none()
    before_value: Any = (
        _coerce_stored_value(existing_row.value, defn) if existing_row else None
    )

    serialized = json.dumps(new_value)
    if existing_row is None:
        db.add(
            TenantSettings(
                tenant_id=tenant_id,
                key=key,
                value=serialized,
            )
        )
    else:
        existing_row.value = serialized
        db.add(existing_row)

    db.add(
        ActivityLog(
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            activity_type=TENANT_SETTING_CHANGED,
            entity_type="tenant_setting",
            entity_id=None,
            summary=f"Setting '{defn.label}' changed",
            route="/admin-settings",
            route_params={"key": key},
            metadata_json={
                "key": key,
                "before": before_value,
                "after": new_value,
                "label": defn.label,
            },
            severity="info",
            visibility_scope="TENANT_ADMIN",
        )
    )
    await db.flush()
    logger.info(
        "tenant_setting_changed: tenant=%s key=%s before=%r after=%r actor=%s",
        tenant_id, key, before_value, new_value, actor_id,
    )
    return new_value


async def get_public_settings(
    db: AsyncSession, tenant_id: int
) -> dict[str, Any]:
    """Every catalog key where ``is_public=True``, typed."""
    catalog = await _load_catalog(db)
    public_keys = {k for k, d in catalog.items() if d.is_public}
    stored = await _load_stored_values(db, tenant_id, keys=public_keys)
    return {
        key: _coerce_stored_value(stored.get(key), defn)
        for key, defn in catalog.items()
        if defn.is_public
    }


async def get_all_settings(
    db: AsyncSession, tenant_id: int
) -> dict[str, Any]:
    """Every catalog key, typed. Unset keys fall back to the catalog default."""
    catalog = await _load_catalog(db)
    stored = await _load_stored_values(db, tenant_id)
    return {
        key: _coerce_stored_value(stored.get(key), defn)
        for key, defn in catalog.items()
    }


async def get_catalog(db: AsyncSession) -> list[dict[str, Any]]:
    """
    Every catalog row rendered as a plain dict — suitable for driving the
    admin UI. Kept in the accessor module so the admin endpoint only
    depends on one import.
    """
    catalog = await _load_catalog(db)
    return [
        {
            "key": defn.key,
            "category": defn.category,
            "data_type": defn.data_type,
            "default_value": _default_as_python(defn),
            "validation": defn.validation or {},
            "label": defn.label,
            "description": defn.description,
            "is_public": defn.is_public,
            "sort_order": defn.sort_order,
        }
        for defn in sorted(
            catalog.values(), key=lambda d: (d.category, d.sort_order, d.key)
        )
    ]


# ─────────────────────────────────────────────────────────────────────────────
# TenantPolicy — typed facade for common consumers
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TenantPolicy:
    """
    Typed snapshot of a tenant's settings, suitable for passing into
    business-logic functions without plumbing an ``AsyncSession`` through
    every call. Built once per request via ``TenantPolicy.for_tenant``.

    The attribute list is intentionally narrow — not every catalog key lives
    here, just the ones that non-endpoint code needs to consult. Adding a
    new attribute requires a default value (keep it in sync with the
    catalog's ``default_value``).
    """

    # Time entry
    time_entry_past_days: int = 30
    time_entry_future_days: int = 7
    max_hours_per_entry: float = 12.0
    max_hours_per_day: float = 12.0
    max_hours_per_week: float = 60.0
    min_submit_weekly_hours: float = 0.0
    allow_partial_week_submit: bool = False
    week_start_day: int = 0

    # Time off
    time_off_past_days: int = 7
    time_off_future_days: int = 365
    time_off_advance_notice_days: int = 3
    time_off_max_consecutive_days: int = 30
    allow_overlapping_time_off: bool = False

    # Security
    max_failed_login_attempts: int = 5
    lockout_duration_minutes: int = 15

    # Notifications
    notification_ttl_days: int = 7
    approval_history_ttl_days: int = 7
    daily_submission_deadline_time: _time = field(
        default_factory=lambda: _time(hour=10, minute=0)
    )
    missing_yesterday_notify_after_hour: int = 8
    manager_missing_team_notify_after_hour: int = 14

    @classmethod
    async def for_tenant(
        cls, db: AsyncSession, tenant_id: int
    ) -> "TenantPolicy":
        values = await get_all_settings(db, tenant_id)
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in values:
                continue
            raw = values[f.name]
            if f.name == "daily_submission_deadline_time" and isinstance(raw, str):
                try:
                    hh, mm = raw.split(":")
                    kwargs[f.name] = _time(int(hh), int(mm))
                    continue
                except (ValueError, AttributeError):
                    continue  # fall back to default via dataclass
            kwargs[f.name] = raw
        return cls(**kwargs)
