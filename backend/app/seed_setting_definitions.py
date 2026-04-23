"""
Seed data for the ``setting_definitions`` catalog.

Idempotent: running the seed twice produces the same result as once. Uses
INSERT ... ON CONFLICT (key) DO NOTHING so existing rows are untouched —
operators who tweak a ``default_value`` or ``validation`` in production
won't have their changes clobbered on a redeploy.

Importable from both Alembic migrations (``upgrade()`` calls ``seed_sync``
with the live connection) and standalone scripts / tests (``seed_async``
works with an async session).

Keep the CATALOG dict in sync with:
  - app/core/tenant_settings.py — the accessor uses the same keys.
  - The UI catalog-driven form on the frontend (fetched dynamically via
    the settings endpoint, so no frontend edits are needed per-key).
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

# ─────────────────────────────────────────────────────────────────────────────
# Catalog
# ─────────────────────────────────────────────────────────────────────────────
#
# Order of fields in each dict:
#   category, data_type, default_value, validation, label, description,
#   is_public, sort_order.
#
# ``default_value`` is always a Python value (int, float, bool, str) — the
# seed helper JSON-encodes it before writing.

CATALOG: dict[str, dict[str, Any]] = {
    # ── time_entry ─────────────────────────────────────────────────
    "time_entry_past_days": {
        "category": "time_entry",
        "data_type": "int",
        "default_value": 30,
        "validation": {"min": 0, "max": 365},
        "label": "Time entry lookback (days)",
        "description": "How many days in the past employees can log time.",
        "is_public": True,
        "sort_order": 10,
    },
    "time_entry_future_days": {
        "category": "time_entry",
        "data_type": "int",
        "default_value": 7,
        "validation": {"min": 0, "max": 90},
        "label": "Time entry future window (days)",
        "description": "How many days ahead employees can log time.",
        "is_public": True,
        "sort_order": 20,
    },
    "max_hours_per_entry": {
        "category": "time_entry",
        "data_type": "float",
        "default_value": 12.0,
        "validation": {"min": 0.5, "max": 24},
        "label": "Max hours per entry",
        "description": "Maximum hours allowed on a single time entry.",
        "is_public": True,
        "sort_order": 30,
    },
    "max_hours_per_day": {
        "category": "time_entry",
        "data_type": "float",
        "default_value": 12.0,
        "validation": {"min": 0.5, "max": 24},
        "label": "Max hours per day",
        "description": "Maximum total hours across all entries on a single day.",
        "is_public": True,
        "sort_order": 40,
    },
    "max_hours_per_week": {
        "category": "time_entry",
        "data_type": "float",
        "default_value": 60.0,
        "validation": {"min": 1, "max": 168},
        "label": "Max hours per week",
        "description": "Maximum total hours across all entries in a single week.",
        "is_public": True,
        "sort_order": 50,
    },
    "min_submit_weekly_hours": {
        "category": "time_entry",
        "data_type": "float",
        "default_value": 0.0,
        "validation": {"min": 0, "max": 168},
        "label": "Minimum weekly hours to submit",
        "description": "Minimum hours an employee must log before they can submit for the week.",
        "is_public": True,
        "sort_order": 60,
    },
    "allow_partial_week_submit": {
        "category": "time_entry",
        "data_type": "bool",
        "default_value": False,
        "validation": {},
        "label": "Allow partial week submission",
        "description": "Allow employees to submit timesheets before the week is complete.",
        "is_public": True,
        "sort_order": 70,
    },
    "week_start_day": {
        "category": "time_entry",
        "data_type": "int",
        "default_value": 0,
        "validation": {"min": 0, "max": 1, "enum": [0, 1]},
        "label": "Week start day",
        "description": "0 = Sunday, 1 = Monday.",
        "is_public": True,
        "sort_order": 80,
    },
    "tenant_default_timezone": {
        "category": "time_entry",
        "data_type": "string",
        "default_value": "UTC",
        "validation": {},
        "label": "Default timezone",
        "description": "IANA timezone name used for deadline calculations and notifications (e.g. America/New_York, Europe/London). Defaults to UTC.",
        "is_public": True,
        "sort_order": 5,
    },
    # ── time_off ───────────────────────────────────────────────────
    "time_off_past_days": {
        "category": "time_off",
        "data_type": "int",
        "default_value": 7,
        "validation": {"min": 0, "max": 365},
        "label": "Time-off request lookback (days)",
        "description": "How many days in the past employees can request time off.",
        "is_public": True,
        "sort_order": 10,
    },
    "time_off_future_days": {
        "category": "time_off",
        "data_type": "int",
        "default_value": 365,
        "validation": {"min": 0, "max": 730},
        "label": "Time-off request future window (days)",
        "description": "How many days ahead employees can request time off.",
        "is_public": True,
        "sort_order": 20,
    },
    "time_off_advance_notice_days": {
        "category": "time_off",
        "data_type": "int",
        "default_value": 3,
        "validation": {"min": 0, "max": 90},
        "label": "Advance notice required (days)",
        "description": "Minimum days notice required before a time-off request date.",
        "is_public": True,
        "sort_order": 30,
    },
    "time_off_max_consecutive_days": {
        "category": "time_off",
        "data_type": "int",
        "default_value": 30,
        "validation": {"min": 1, "max": 365},
        "label": "Max consecutive days off",
        "description": "Maximum number of consecutive days allowed in a single time-off request.",
        "is_public": True,
        "sort_order": 40,
    },
    "allow_overlapping_time_off": {
        "category": "time_off",
        "data_type": "bool",
        "default_value": False,
        "validation": {},
        "label": "Allow overlapping time-off requests",
        "description": "Allow multiple employees to have approved time off on the same day.",
        "is_public": True,
        "sort_order": 50,
    },
    # ── security ───────────────────────────────────────────────────
    "max_failed_login_attempts": {
        "category": "security",
        "data_type": "int",
        "default_value": 5,
        "validation": {"min": 1, "max": 20},
        "label": "Max failed login attempts",
        "description": "Number of failed logins before an account is temporarily locked.",
        "is_public": False,
        "sort_order": 10,
    },
    "lockout_duration_minutes": {
        "category": "security",
        "data_type": "int",
        "default_value": 15,
        "validation": {"min": 1, "max": 1440},
        "label": "Lockout duration (minutes)",
        "description": "How long an account remains locked after too many failed login attempts.",
        "is_public": False,
        "sort_order": 20,
    },
    # ── reminders ──────────────────────────────────────────────────
    "reminder_internal_enabled": {
        "category": "reminders",
        "data_type": "bool",
        "default_value": False,
        "validation": {},
        "label": "Enable internal reminders",
        "description": "Send reminder emails to employees before the weekly timesheet deadline.",
        "is_public": False,
        "sort_order": 10,
    },
    "reminder_internal_deadline_day": {
        "category": "reminders",
        "data_type": "string",
        "default_value": "friday",
        "validation": {
            "enum": ["monday", "tuesday", "wednesday", "thursday", "friday"]
        },
        "label": "Deadline day",
        "description": "Day of the week timesheets are due.",
        "is_public": False,
        "sort_order": 20,
    },
    "reminder_internal_deadline_time": {
        "category": "reminders",
        "data_type": "time",
        "default_value": "17:00",
        "validation": {},
        "label": "Deadline time",
        "description": "Time of day timesheets are due (24-hour format, tenant timezone).",
        "is_public": False,
        "sort_order": 30,
    },
    "reminder_internal_lock_enabled": {
        "category": "reminders",
        "data_type": "bool",
        "default_value": False,
        "validation": {},
        "label": "Auto-lock on missed deadline",
        "description": "Automatically lock timesheets for employees who miss the deadline.",
        "is_public": False,
        "sort_order": 40,
    },
    "reminder_internal_recipients": {
        "category": "reminders",
        "data_type": "string",
        "default_value": "all",
        "validation": {},
        "label": "Reminder recipients",
        "description": "Comma-separated user IDs to remind, or 'all' for every eligible employee.",
        "is_public": False,
        "sort_order": 50,
    },
    "reminder_external_enabled": {
        "category": "reminders",
        "data_type": "bool",
        "default_value": False,
        "validation": {},
        "label": "Enable external contractor reminders",
        "description": "Send monthly reminder emails to external contractors.",
        "is_public": False,
        "sort_order": 60,
    },
    "reminder_external_deadline_day_of_month": {
        "category": "reminders",
        "data_type": "int",
        "default_value": 28,
        "validation": {"min": 1, "max": 31},
        "label": "External deadline day of month",
        "description": "Day of the month external timesheets are due.",
        "is_public": False,
        "sort_order": 70,
    },
    "reminder_external_deadline_time": {
        "category": "reminders",
        "data_type": "time",
        "default_value": "17:00",
        "validation": {},
        "label": "External deadline time",
        "description": "Time of day external timesheets are due.",
        "is_public": False,
        "sort_order": 80,
    },
    # ── notifications ──────────────────────────────────────────────
    "notification_ttl_days": {
        "category": "notifications",
        "data_type": "int",
        "default_value": 7,
        "validation": {"min": 1, "max": 90},
        "label": "Notification retention (days)",
        "description": "How many days notifications remain visible before expiring.",
        "is_public": False,
        "sort_order": 10,
    },
    "approval_history_ttl_days": {
        "category": "notifications",
        "data_type": "int",
        "default_value": 7,
        "validation": {"min": 1, "max": 365},
        "label": "Approval history window (days)",
        "description": "Default lookback window for approval history.",
        "is_public": False,
        "sort_order": 20,
    },
    "daily_submission_deadline_time": {
        "category": "notifications",
        "data_type": "time",
        "default_value": "10:00",
        "validation": {},
        "label": "Daily submission cutoff time",
        "description": "Time after which the team daily overview shows entries as overdue.",
        "is_public": False,
        "sort_order": 30,
    },
    "missing_yesterday_notify_after_hour": {
        "category": "notifications",
        "data_type": "int",
        "default_value": 8,
        "validation": {"min": 0, "max": 23},
        "label": "Missing-yesterday notification hour",
        "description": "Hour of day (UTC) after which the 'missing yesterday entry' notification appears.",
        "is_public": False,
        "sort_order": 40,
    },
    "manager_missing_team_notify_after_hour": {
        "category": "notifications",
        "data_type": "int",
        "default_value": 14,
        "validation": {"min": 0, "max": 23},
        "label": "Manager missing-team notification hour",
        "description": "Hour of day (UTC) after which managers are notified about missing team entries.",
        "is_public": False,
        "sort_order": 50,
    },
    # ── email ──────────────────────────────────────────────────────
    "smtp_host": {
        "category": "email",
        "data_type": "string",
        "default_value": "",
        "validation": {},
        "label": "SMTP host",
        "description": "Outbound email server hostname. Leave blank to use platform default.",
        "is_public": False,
        "sort_order": 10,
    },
    "smtp_port": {
        "category": "email",
        "data_type": "int",
        "default_value": 587,
        "validation": {"min": 1, "max": 65535},
        "label": "SMTP port",
        "description": "Outbound email server port.",
        "is_public": False,
        "sort_order": 20,
    },
    "smtp_username": {
        "category": "email",
        "data_type": "string",
        "default_value": "",
        "validation": {},
        "label": "SMTP username",
        "description": "Username for SMTP authentication.",
        "is_public": False,
        "sort_order": 30,
    },
    "smtp_password": {
        "category": "email",
        "data_type": "string",
        "default_value": "",
        "validation": {},
        "label": "SMTP password",
        "description": "Password for SMTP authentication. Stored encrypted.",
        "is_public": False,
        "sort_order": 40,
    },
    "smtp_from_address": {
        "category": "email",
        "data_type": "string",
        "default_value": "",
        "validation": {},
        "label": "From address",
        "description": "Email address that appears in the From field.",
        "is_public": False,
        "sort_order": 50,
    },
    "smtp_from_name": {
        "category": "email",
        "data_type": "string",
        "default_value": "",
        "validation": {},
        "label": "From name",
        "description": "Display name that appears in the From field.",
        "is_public": False,
        "sort_order": 60,
    },
    "smtp_use_tls": {
        "category": "email",
        "data_type": "bool",
        "default_value": True,
        "validation": {},
        "label": "Use TLS",
        "description": "Enable TLS encryption for outbound email.",
        "is_public": False,
        "sort_order": 70,
    },
    # ── email ingestion / fetch scheduling ────────────────────────
    # These keys predate the catalog and are written by the Mailboxes admin
    # UI, not the main settings form. Included here so PATCH /tenant-settings
    # still accepts them after the catalog-strict validation landed.
    "fetch_emails_enabled": {
        "category": "email",
        "data_type": "bool",
        "default_value": False,
        "validation": {},
        "label": "Enable scheduled email fetch",
        "description": "Automatically fetch email from configured mailboxes on a schedule.",
        "is_public": False,
        "sort_order": 100,
    },
    "fetch_emails_interval_minutes": {
        "category": "email",
        "data_type": "int",
        "default_value": 15,
        "validation": {"min": 1, "max": 1440},
        "label": "Fetch interval (minutes)",
        "description": "How often to poll mailboxes for new email.",
        "is_public": False,
        "sort_order": 110,
    },
    "fetch_emails_days": {
        "category": "email",
        "data_type": "string",
        "default_value": "mon,tue,wed,thu,fri",
        "validation": {},
        "label": "Fetch days",
        "description": "Comma-separated days of the week when fetch runs (e.g. mon,tue,wed,thu,fri).",
        "is_public": False,
        "sort_order": 120,
    },
    "fetch_emails_start_time": {
        "category": "email",
        "data_type": "time",
        "default_value": "08:00",
        "validation": {},
        "label": "Fetch start time",
        "description": "Time of day (24-hour) when scheduled fetch begins each day.",
        "is_public": False,
        "sort_order": 130,
    },
    "fetch_emails_end_time": {
        "category": "email",
        "data_type": "time",
        "default_value": "20:00",
        "validation": {},
        "label": "Fetch end time",
        "description": "Time of day (24-hour) when scheduled fetch stops each day.",
        "is_public": False,
        "sort_order": 140,
    },
    "license_key": {
        "category": "licensing",
        "data_type": "string",
        "default_value": "",
        "validation": {},
        "label": "License key",
        "description": "Signed license JWT. Set via LICENSE_KEY env var or stored here as a fallback.",
        "is_public": False,
        "sort_order": 10,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Seed helpers
# ─────────────────────────────────────────────────────────────────────────────


def seed_sync(connection) -> int:
    """
    Synchronous seed, suitable for Alembic ``op.get_bind()`` connections.

    Returns the number of rows inserted. Existing rows are left alone
    (ON CONFLICT DO NOTHING) so operator edits aren't overwritten.
    """
    dialect = connection.dialect.name
    inserted = 0

    for key, defn in CATALOG.items():
        params = {
            "key": key,
            "category": defn["category"],
            "data_type": defn["data_type"],
            "default_value": json.dumps(defn["default_value"]),
            "validation": json.dumps(defn.get("validation") or {}),
            "label": defn["label"],
            "description": defn["description"],
            "is_public": defn.get("is_public", False),
            "sort_order": defn.get("sort_order", 0),
            "added_in": defn.get("added_in", "1.0.0"),
        }

        if dialect == "postgresql":
            stmt = text(
                """
                INSERT INTO setting_definitions (
                    key, category, data_type, default_value, validation,
                    label, description, is_public, sort_order, added_in
                ) VALUES (
                    :key, :category, :data_type,
                    CAST(:default_value AS jsonb), CAST(:validation AS jsonb),
                    :label, :description, :is_public, :sort_order, :added_in
                )
                ON CONFLICT (key) DO NOTHING
                """
            )
        else:
            # SQLite (test harness): JSON is text, ON CONFLICT uses INSERT OR IGNORE.
            stmt = text(
                """
                INSERT OR IGNORE INTO setting_definitions (
                    key, category, data_type, default_value, validation,
                    label, description, is_public, sort_order, added_in
                ) VALUES (
                    :key, :category, :data_type, :default_value, :validation,
                    :label, :description, :is_public, :sort_order, :added_in
                )
                """
            )
        result = connection.execute(stmt, params)
        inserted += result.rowcount if result.rowcount and result.rowcount > 0 else 0

    return inserted


async def seed_async(session) -> int:
    """Async counterpart for tests / standalone scripts using AsyncSession."""
    # Run the sync body inside the session's sync connection via run_sync.
    async def _run(sync_session):  # pragma: no cover - trivial wrapper
        return seed_sync(sync_session.connection())

    return await session.run_sync(lambda s: seed_sync(s.connection()))


if __name__ == "__main__":  # pragma: no cover - manual invocation
    import asyncio

    from app.db import AsyncSessionLocal

    async def _main() -> None:
        async with AsyncSessionLocal() as session:
            inserted = await seed_async(session)
            await session.commit()
            print(f"Seeded setting_definitions: +{inserted} rows")

    asyncio.run(_main())
