"""
Seed data for the capability-based permission framework.

Idempotent: running the seed repeatedly does not duplicate rows. The seed is
shared by Alembic migration 031 and by async tests that create metadata from
the ORM models directly.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import text

PERMISSIONS = [
    ("time_entry.read_own", "Read own time entries", "time_entry"),
    ("time_entry.write_own", "Create and edit own time entries", "time_entry"),
    ("time_entry.submit_own", "Submit own time entries for approval", "time_entry"),
    ("time_entry.read_team", "Read time entries for managed team", "time_entry"),
    ("time_entry.approve", "Approve or reject time entries", "time_entry"),
    ("time_entry.approve_any", "Approve or reject any entry in tenant", "time_entry"),
    ("time_entry.unlock", "Unlock a locked timesheet", "time_entry"),
    ("time_off.read_own", "Read own time-off requests", "time_off"),
    ("time_off.write_own", "Create and edit own time-off requests", "time_off"),
    ("time_off.submit_own", "Submit own time-off requests", "time_off"),
    ("time_off.approve", "Approve or reject time-off requests", "time_off"),
    ("time_off.approve_any", "Approve or reject any request in tenant", "time_off"),
    ("user.read", "Read user profiles in tenant", "user"),
    ("user.manage", "Create, update, delete users", "user"),
    ("user.reset_password", "Reset another user's password", "user"),
    ("client.read", "Read clients", "catalog"),
    ("client.manage", "Create, update, delete clients", "catalog"),
    ("project.read", "Read projects", "catalog"),
    ("project.manage", "Create, update, delete projects", "catalog"),
    ("project.assign_access", "Assign project access to team members", "catalog"),
    ("task.manage", "Create, update, delete tasks", "catalog"),
    ("department.manage", "Manage departments", "catalog"),
    ("leave_type.manage", "Manage leave types", "catalog"),
    ("ingestion.review", "Review and act on ingested timesheets", "ingestion"),
    ("ingestion.fetch", "Trigger email fetch", "ingestion"),
    ("mailbox.manage", "Manage mailboxes and email mappings", "ingestion"),
    ("tenant.settings.read", "Read tenant settings", "admin"),
    ("tenant.settings.update", "Update tenant settings", "admin"),
    ("audit.read", "Read the audit trail", "admin"),
    ("dashboard.team", "View team dashboard and analytics", "admin"),
    ("tenant.create", "Create new tenants", "platform"),
    ("tenant.manage", "Update tenant status and configuration", "platform"),
    ("service_token.issue", "Issue service tokens", "platform"),
    ("platform.settings.manage", "Manage platform-wide settings", "platform"),
    ("platform.admin.access", "Access platform administration UI", "platform"),
]

SYSTEM_ROLES = {
    "EMPLOYEE": {
        "name": "Employee",
        "permissions": [
            "time_entry.read_own",
            "time_entry.write_own",
            "time_entry.submit_own",
            "time_off.read_own",
            "time_off.write_own",
            "time_off.submit_own",
            "client.read",
            "project.read",
            "tenant.settings.read",
        ],
    },
    "MANAGER": {
        "name": "Manager",
        "permissions": [
            "time_entry.read_own",
            "time_entry.write_own",
            "time_entry.submit_own",
            "time_off.read_own",
            "time_off.write_own",
            "time_off.submit_own",
            "time_entry.read_team",
            "time_entry.approve",
            "time_off.approve",
            "project.assign_access",
            "user.read",
            "dashboard.team",
            "client.read",
            "project.read",
            "tenant.settings.read",
        ],
    },
    "SENIOR_MANAGER": {
        "name": "Senior Manager",
        "permissions": [
            "time_entry.read_own",
            "time_entry.write_own",
            "time_entry.submit_own",
            "time_off.read_own",
            "time_off.write_own",
            "time_off.submit_own",
            "time_entry.read_team",
            "time_entry.approve",
            "time_off.approve",
            "project.assign_access",
            "user.read",
            "dashboard.team",
            "client.read",
            "project.read",
            "tenant.settings.read",
        ],
    },
    "CEO": {
        "name": "CEO",
        "permissions": [
            "time_entry.read_own",
            "time_entry.write_own",
            "time_entry.submit_own",
            "time_off.read_own",
            "time_off.write_own",
            "time_off.submit_own",
            "time_entry.read_team",
            "time_entry.approve_any",
            "time_off.approve_any",
            "user.read",
            "dashboard.team",
            "client.read",
            "project.read",
            "tenant.settings.read",
        ],
    },
    "ADMIN": {
        "name": "Administrator",
        "permissions": [
            "time_entry.read_own",
            "time_entry.write_own",
            "time_entry.submit_own",
            "time_off.read_own",
            "time_off.write_own",
            "time_off.submit_own",
            "time_entry.read_team",
            "time_entry.approve_any",
            "time_off.approve_any",
            "time_entry.unlock",
            "user.read",
            "user.manage",
            "user.reset_password",
            "client.read",
            "client.manage",
            "project.read",
            "project.manage",
            "project.assign_access",
            "task.manage",
            "department.manage",
            "leave_type.manage",
            "ingestion.review",
            "ingestion.fetch",
            "mailbox.manage",
            "tenant.settings.read",
            "tenant.settings.update",
            "audit.read",
            "dashboard.team",
        ],
    },
    "PLATFORM_ADMIN": {
        "name": "Platform Administrator",
        "permissions": [
            "time_entry.read_own",
            "time_entry.write_own",
            "time_entry.submit_own",
            "time_off.read_own",
            "time_off.write_own",
            "time_off.submit_own",
            "time_entry.read_team",
            "time_entry.approve_any",
            "time_off.approve_any",
            "time_entry.unlock",
            "user.read",
            "user.manage",
            "user.reset_password",
            "client.read",
            "client.manage",
            "project.read",
            "project.manage",
            "project.assign_access",
            "task.manage",
            "department.manage",
            "leave_type.manage",
            "ingestion.review",
            "ingestion.fetch",
            "mailbox.manage",
            "tenant.settings.read",
            "tenant.settings.update",
            "audit.read",
            "dashboard.team",
            "tenant.create",
            "tenant.manage",
            "service_token.issue",
            "platform.settings.manage",
            "platform.admin.access",
        ],
    },
    "REVIEWER": {
        "name": "Reviewer",
        "permissions": ["ingestion.review", "ingestion.fetch"],
    },
}

_ROLE_INSERT = """
    INSERT INTO roles (tenant_id, code, name, is_system)
    SELECT NULL, :code, :name, :is_system
    WHERE NOT EXISTS (
        SELECT 1
        FROM roles
        WHERE tenant_id IS NULL AND code = :code
    )
"""


def _coerce_effective_from(value) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return date.today()
    return date.today()


def seed_sync(connection) -> int:
    dialect = connection.dialect.name
    inserted = 0

    permission_insert = text(
        """
        INSERT INTO permissions (code, description, category)
        VALUES (:code, :description, :category)
        ON CONFLICT (code) DO NOTHING
        """
        if dialect == "postgresql"
        else """
        INSERT OR IGNORE INTO permissions (code, description, category)
        VALUES (:code, :description, :category)
        """
    )
    role_permission_insert = text(
        """
        INSERT INTO role_permissions (role_id, permission_code)
        VALUES (:role_id, :permission_code)
        ON CONFLICT (role_id, permission_code) DO NOTHING
        """
        if dialect == "postgresql"
        else """
        INSERT OR IGNORE INTO role_permissions (role_id, permission_code)
        VALUES (:role_id, :permission_code)
        """
    )
    role_assignment_insert = text(
        """
        INSERT INTO role_assignments (
            user_id,
            role_id,
            scope_type,
            scope_ref_id,
            effective_from,
            effective_to,
            granted_by
        ) VALUES (
            :user_id,
            :role_id,
            :scope_type,
            :scope_ref_id,
            :effective_from,
            NULL,
            NULL
        )
        ON CONFLICT (user_id, role_id, effective_from) DO NOTHING
        """
        if dialect == "postgresql"
        else """
        INSERT OR IGNORE INTO role_assignments (
            user_id,
            role_id,
            scope_type,
            scope_ref_id,
            effective_from,
            effective_to,
            granted_by
        ) VALUES (
            :user_id,
            :role_id,
            :scope_type,
            :scope_ref_id,
            :effective_from,
            NULL,
            NULL
        )
        """
    )

    for code, description, category in PERMISSIONS:
        result = connection.execute(
            permission_insert,
            {"code": code, "description": description, "category": category},
        )
        inserted += max(result.rowcount or 0, 0)

    for code, role_def in SYSTEM_ROLES.items():
        result = connection.execute(
            text(_ROLE_INSERT),
            {"code": code, "name": role_def["name"], "is_system": True},
        )
        inserted += max(result.rowcount or 0, 0)

    role_rows = connection.execute(
        text("SELECT id, code FROM roles WHERE tenant_id IS NULL")
    ).mappings()
    role_ids = {row["code"]: row["id"] for row in role_rows}

    for code, role_def in SYSTEM_ROLES.items():
        role_id = role_ids.get(code)
        if role_id is None:
            continue
        for permission_code in role_def["permissions"]:
            result = connection.execute(
                role_permission_insert,
                {"role_id": role_id, "permission_code": permission_code},
            )
            inserted += max(result.rowcount or 0, 0)

    user_rows = connection.execute(
        text(
            """
            SELECT id, role, can_review, tenant_id, created_at
            FROM users
            """
        )
    ).mappings()
    for user_row in user_rows:
        primary_role_id = role_ids.get(user_row["role"])
        if primary_role_id is None:
            continue
        effective_from = _coerce_effective_from(user_row["created_at"])
        scope_type = "global" if user_row["role"] == "PLATFORM_ADMIN" else "tenant"
        result = connection.execute(
            role_assignment_insert,
            {
                "user_id": user_row["id"],
                "role_id": primary_role_id,
                "scope_type": scope_type,
                "scope_ref_id": user_row["tenant_id"],
                "effective_from": effective_from,
            },
        )
        inserted += max(result.rowcount or 0, 0)

        if (
            user_row["can_review"]
            and user_row["role"] not in {"ADMIN", "PLATFORM_ADMIN"}
            and "REVIEWER" in role_ids
        ):
            result = connection.execute(
                role_assignment_insert,
                {
                    "user_id": user_row["id"],
                    "role_id": role_ids["REVIEWER"],
                    "scope_type": "tenant",
                    "scope_ref_id": user_row["tenant_id"],
                    "effective_from": effective_from,
                },
            )
            inserted += max(result.rowcount or 0, 0)

    return inserted


async def seed_async(session) -> int:
    return await session.run_sync(lambda s: seed_sync(s.connection()))
