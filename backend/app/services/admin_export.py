"""Admin export service: build CSV/XLSX exports for users, clients, and
approved timesheets with filters. ADMIN-only.

Three export types:
  - users        : flat user list (name, email(s), phone(s), role, type, ...)
  - clients      : client list (name, domains, status, project count)
  - timesheets   : approved time entries aggregated by employee x client/project
                   x period, one row per group. Internal users have client blank.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.client import Client
from app.models.project import Project
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.user import User, UserRole
from app.models.user_email_alias import UserEmailAlias


def _format_period(start: date, end: date) -> str:
    return f"{start.strftime('%b %-d, %Y') if hasattr(start, 'strftime') else start} to {end.strftime('%b %-d, %Y') if hasattr(end, 'strftime') else end}"


def _format_date_range(start: date, end: date) -> str:
    s = f"{start:%b %d, %Y}".replace(" 0", " ")
    e = f"{end:%b %d, %Y}".replace(" 0", " ")
    return f"{s} to {e}"


def _format_decimal(value: Decimal | float | int) -> str:
    if isinstance(value, Decimal):
        if value == value.to_integral():
            return str(int(value))
        return f"{value:.2f}"
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}"
    return str(value)


def _csv_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _xlsx_bytes(headers: list[str], rows: list[list[str]], sheet_name: str = "Sheet1") -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]
    ws.append(headers)
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()


def serialize(
    headers: list[str],
    rows: list[list[str]],
    fmt: str,
    sheet_name: str = "Export",
) -> tuple[bytes, str, str]:
    """Return (content_bytes, mime_type, filename_extension)."""
    if fmt == "xlsx":
        return _xlsx_bytes(headers, rows, sheet_name), (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ), "xlsx"
    return _csv_bytes(headers, rows), "text/csv", "csv"


# ---------------------------------------------------------------------------
# Users export
# ---------------------------------------------------------------------------

USERS_HEADERS = [
    "Full Name",
    "Email",
    "Extra Emails",
    "Primary Phone",
    "Extra Phones",
    "Role",
    "User Type",
    "Title",
    "Department",
    "Default Client",
    "Manager",
    "Status",
]


async def export_users(
    db: AsyncSession,
    tenant_id: int,
    *,
    user_type: str = "all",          # all | internal | external
    role: Optional[str] = None,
    status_filter: str = "all",      # all | active | inactive
    client_id: Optional[int] = None,
    department: Optional[str] = None,
) -> tuple[list[str], list[list[str]]]:
    stmt = (
        select(User)
        .where(User.tenant_id == tenant_id)
        .options(
            selectinload(User.email_aliases),
            selectinload(User.manager_assignment),
        )
        .order_by(User.full_name.asc())
    )
    if user_type == "internal":
        stmt = stmt.where(User.is_external.is_(False))
    elif user_type == "external":
        stmt = stmt.where(User.is_external.is_(True))
    if role:
        stmt = stmt.where(User.role == UserRole(role))
    if status_filter == "active":
        stmt = stmt.where(User.is_active.is_(True))
    elif status_filter == "inactive":
        stmt = stmt.where(User.is_active.is_(False))
    if client_id is not None:
        stmt = stmt.where(User.default_client_id == client_id)
    if department:
        stmt = stmt.where(User.department == department)

    result = await db.execute(stmt)
    users = list(result.scalars().unique().all())

    # Resolve client names + manager names in batch (avoid N+1).
    client_ids = {u.default_client_id for u in users if u.default_client_id}
    manager_ids = {
        u.manager_assignment.manager_id for u in users
        if u.manager_assignment and u.manager_assignment.manager_id
    }

    client_name_by_id: dict[int, str] = {}
    if client_ids:
        cres = await db.execute(select(Client.id, Client.name).where(Client.id.in_(client_ids)))
        client_name_by_id = {row.id: row.name for row in cres}

    manager_name_by_id: dict[int, str] = {}
    if manager_ids:
        mres = await db.execute(select(User.id, User.full_name).where(User.id.in_(manager_ids)))
        manager_name_by_id = {row.id: row.full_name for row in mres}

    rows: list[list[str]] = []
    for u in users:
        extra_emails = ", ".join(a.email for a in (u.email_aliases or []))
        phones = list(u.phones or [])
        primary_phone = phones[0] if phones else ""
        extra_phones = ", ".join(phones[1:]) if len(phones) > 1 else ""

        manager_name = ""
        if u.manager_assignment and u.manager_assignment.manager_id:
            manager_name = manager_name_by_id.get(u.manager_assignment.manager_id, "")

        client_name = client_name_by_id.get(u.default_client_id, "") if u.default_client_id else ""

        rows.append([
            u.full_name or "",
            u.email or "",
            extra_emails,
            primary_phone,
            extra_phones,
            u.role.value if u.role else "",
            "External" if u.is_external else "Internal",
            u.title or "",
            u.department or "",
            client_name,
            manager_name,
            "Active" if u.is_active else "Inactive",
        ])

    return USERS_HEADERS, rows


# ---------------------------------------------------------------------------
# Clients export
# ---------------------------------------------------------------------------

CLIENTS_HEADERS = [
    "Name",
    "Email Domains",
    "Contact Name",
    "Contact Email",
    "Contact Phone",
    "Project Count",
    "Active Project Count",
]


async def export_clients(
    db: AsyncSession,
    tenant_id: int,
) -> tuple[list[str], list[list[str]]]:
    stmt = (
        select(Client)
        .where(Client.tenant_id == tenant_id)
        .options(
            selectinload(Client.projects),
            selectinload(Client.email_domains),
        )
        .order_by(Client.name.asc())
    )
    result = await db.execute(stmt)
    clients = list(result.scalars().unique().all())

    rows: list[list[str]] = []
    for c in clients:
        projects = list(c.projects or [])
        active_count = sum(1 for p in projects if getattr(p, "is_active", True))
        domains = ", ".join(d.domain for d in (c.email_domains or []) if getattr(d, "domain", None))
        rows.append([
            c.name or "",
            domains,
            c.contact_name or "",
            c.contact_email or "",
            c.contact_phone or "",
            str(len(projects)),
            str(active_count),
        ])
    return CLIENTS_HEADERS, rows


# ---------------------------------------------------------------------------
# Timesheets export
# ---------------------------------------------------------------------------

TIMESHEETS_HEADERS = [
    "Employee Name",
    "User Type",
    "Client",
    "Project",
    "Period",
    "Total Hours",
]


async def export_approved_timesheets(
    db: AsyncSession,
    tenant_id: int,
    *,
    period_start: date,
    period_end: date,
    user_type: str = "all",            # all | internal | external
    user_id: Optional[int] = None,
    client_id: Optional[int] = None,
    project_id: Optional[int] = None,
) -> tuple[list[str], list[list[str]]]:
    """Aggregate approved entries into one row per employee x client/project.

    External users group by client (project blank). Internal users group by
    project (client blank, per requirement).
    """
    stmt = (
        select(
            TimeEntry.user_id,
            TimeEntry.project_id,
            func.sum(TimeEntry.hours).label("total_hours"),
        )
        .where(TimeEntry.tenant_id == tenant_id)
        .where(TimeEntry.status == TimeEntryStatus.APPROVED)
        .where(TimeEntry.entry_date >= period_start)
        .where(TimeEntry.entry_date <= period_end)
        .group_by(TimeEntry.user_id, TimeEntry.project_id)
    )
    if user_id is not None:
        stmt = stmt.where(TimeEntry.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(TimeEntry.project_id == project_id)

    result = await db.execute(stmt)
    raw_rows = list(result.all())

    if not raw_rows:
        return TIMESHEETS_HEADERS, []

    user_ids = {r.user_id for r in raw_rows}
    project_ids = {r.project_id for r in raw_rows if r.project_id}

    # Load users (need is_external + default_client_id + name).
    users_res = await db.execute(
        select(User).where(User.id.in_(user_ids))
    )
    users_by_id: dict[int, User] = {u.id: u for u in users_res.scalars().all()}

    # Apply user-type / specific user filter at this layer (post-aggregation
    # is fine since groupings are by user already).
    if user_type == "internal":
        users_by_id = {uid: u for uid, u in users_by_id.items() if not u.is_external}
    elif user_type == "external":
        users_by_id = {uid: u for uid, u in users_by_id.items() if u.is_external}

    # Load projects -> client mapping.
    projects_by_id: dict[int, Project] = {}
    if project_ids:
        proj_res = await db.execute(
            select(Project).where(Project.id.in_(project_ids))
        )
        projects_by_id = {p.id: p for p in proj_res.scalars().all()}

    # Need client names for external users and client_id filter.
    client_ids = {p.client_id for p in projects_by_id.values() if p.client_id}
    client_ids.update(u.default_client_id for u in users_by_id.values() if u.default_client_id)
    client_name_by_id: dict[int, str] = {}
    if client_ids:
        cres = await db.execute(select(Client.id, Client.name).where(Client.id.in_(client_ids)))
        client_name_by_id = {row.id: row.name for row in cres}

    period_str = _format_date_range(period_start, period_end)

    # Re-aggregate: external users group by client, internal by project.
    external_buckets: dict[tuple[int, Optional[int]], Decimal] = defaultdict(lambda: Decimal("0"))
    internal_buckets: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal("0"))

    for r in raw_rows:
        u = users_by_id.get(r.user_id)
        if u is None:
            continue
        proj = projects_by_id.get(r.project_id) if r.project_id else None
        if u.is_external:
            # Client preference: project's client, else user's default client.
            cid: Optional[int] = (proj.client_id if proj and proj.client_id else u.default_client_id)
            if client_id is not None and cid != client_id:
                continue
            external_buckets[(u.id, cid)] += Decimal(str(r.total_hours))
        else:
            if not r.project_id:
                continue
            if client_id is not None:
                proj_client = proj.client_id if proj else None
                if proj_client != client_id:
                    continue
            internal_buckets[(u.id, r.project_id)] += Decimal(str(r.total_hours))

    rows: list[list[str]] = []

    for (uid, cid), total in external_buckets.items():
        u = users_by_id[uid]
        cname = client_name_by_id.get(cid, "") if cid else ""
        rows.append([
            u.full_name,
            "External",
            cname,
            "",
            period_str,
            _format_decimal(total),
        ])

    for (uid, pid), total in internal_buckets.items():
        u = users_by_id[uid]
        proj = projects_by_id.get(pid)
        pname = proj.name if proj else ""
        rows.append([
            u.full_name,
            "Internal",
            "",
            pname,
            period_str,
            _format_decimal(total),
        ])

    rows.sort(key=lambda r: (r[0].lower(), r[2].lower(), r[3].lower()))
    return TIMESHEETS_HEADERS, rows
