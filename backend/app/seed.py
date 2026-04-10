"""Idempotent seed script focused on complete senior-manager demo data."""

import asyncio
import random
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db import AsyncSessionLocal, init_db
from app.models.assignments import EmployeeManagerAssignment, UserProjectAccess
from app.models.client import Client
from app.models.project import Project
from app.models.tenant import Tenant, TenantStatus
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.user import User, UserRole

DEFAULT_PASSWORD = "password"


async def _ensure_system_service_user(
    db: AsyncSession,
    tenant_id: int,
) -> User:
    """
    Creates a system user for the ingestion platform sync.
    This user is set as `approved_by` for all ingestion-pushed time entries.
    It cannot meaningfully log in (random unhashed password).
    """
    username = f"system_ingestion_{tenant_id}"
    email = f"system_ingestion_{tenant_id}@system.internal"

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            tenant_id=tenant_id,
            email=email,
            username=username,
            full_name="Ingestion System",
            hashed_password=get_password_hash(secrets.token_urlsafe(48)),
            role=UserRole.EMPLOYEE,
            is_active=True,
            has_changed_password=True,
            can_review=False,
            is_external=False,
        )
        db.add(user)
        await db.commit()
        print(f"   Created system service user for tenant {tenant_id}: {username}")

    return user


async def _ensure_default_tenant(db: AsyncSession) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.slug == "default"))
    tenant = result.scalar_one_or_none()
    if tenant:
        return tenant
    tenant = Tenant(
        name="Default Tenant",
        slug="default",
        status=TenantStatus.active,
        ingestion_enabled=True,
    )
    db.add(tenant)
    await db.flush()
    return tenant


async def _enable_ingestion_for_demo_tenant(db: AsyncSession) -> None:
    result = await db.execute(select(Tenant).where(Tenant.slug == "default"))
    tenant = result.scalar_one_or_none()
    if tenant and not tenant.ingestion_enabled:
        tenant.ingestion_enabled = True
        db.add(tenant)
        await db.flush()


async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.strip().lower()))
    return result.scalar_one_or_none()


async def _ensure_user(
    db: AsyncSession,
    *,
    email: str,
    username: str,
    full_name: str,
    title: str,
    department: str,
    role: UserRole,
    tenant_id: int,
) -> User:
    existing = await _get_user_by_email(db, email)
    if existing:
        existing.username = username
        existing.full_name = full_name
        existing.title = title
        existing.department = department
        existing.role = role
        existing.is_active = True
        existing.tenant_id = tenant_id
        existing.hashed_password = get_password_hash(DEFAULT_PASSWORD)
        existing.has_changed_password = True
        db.add(existing)
        await db.flush()
        return existing

    user = User(
        email=email,
        username=username,
        full_name=full_name,
        title=title,
        department=department,
        role=role,
        is_active=True,
        tenant_id=tenant_id,
        hashed_password=get_password_hash(DEFAULT_PASSWORD),
        has_changed_password=True,
        email_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _ensure_client(db: AsyncSession, name: str, tenant_id: int) -> Client:
    result = await db.execute(select(Client).where(Client.name == name, Client.tenant_id == tenant_id))
    client = result.scalar_one_or_none()
    if client:
        return client
    client = Client(name=name, tenant_id=tenant_id)
    db.add(client)
    await db.flush()
    return client


async def _ensure_project(
    db: AsyncSession,
    *,
    name: str,
    client_id: int,
    billable_rate: Decimal,
    code: str,
    description: str,
    tenant_id: int,
) -> Project:
    result = await db.execute(select(Project).where(Project.name == name, Project.tenant_id == tenant_id))
    project = result.scalar_one_or_none()
    if project:
        project.client_id = client_id
        project.billable_rate = billable_rate
        project.code = code
        project.description = description
        project.is_active = True
        db.add(project)
        await db.flush()
        return project

    project = Project(
        name=name,
        client_id=client_id,
        billable_rate=billable_rate,
        code=code,
        description=description,
        is_active=True,
        tenant_id=tenant_id,
    )
    db.add(project)
    await db.flush()
    return project


async def _ensure_manager_assignment(db: AsyncSession, *, employee_id: int, manager_id: int) -> None:
    result = await db.execute(
        select(EmployeeManagerAssignment).where(
            EmployeeManagerAssignment.employee_id == employee_id)
    )
    assignment = result.scalar_one_or_none()
    if assignment:
        assignment.manager_id = manager_id
        db.add(assignment)
        return

    db.add(EmployeeManagerAssignment(
        employee_id=employee_id, manager_id=manager_id))


async def _ensure_project_access(db: AsyncSession, *, user_id: int, project_ids: list[int]) -> None:
    result = await db.execute(select(UserProjectAccess).where(UserProjectAccess.user_id == user_id))
    existing_ids = {row.project_id for row in result.scalars().all()}
    for project_id in project_ids:
        if project_id in existing_ids:
            continue
        db.add(UserProjectAccess(user_id=user_id, project_id=project_id))


async def _ensure_recent_time_entries(
    db: AsyncSession,
    *,
    user_id: int,
    project_ids: list[int],
    approver_id: int | None,
    seed: int,
    tenant_id: int,
) -> None:
    today = date.today()
    recent_cutoff = today - timedelta(days=20)

    existing_count = await db.scalar(
        select(TimeEntry.id)
        .where(TimeEntry.user_id == user_id)
        .where(TimeEntry.entry_date >= recent_cutoff)
        .limit(1)
    )
    if existing_count is not None:
        return

    rng = random.Random(seed)
    statuses = [TimeEntryStatus.DRAFT,
                TimeEntryStatus.SUBMITTED, TimeEntryStatus.APPROVED]

    for days_ago in range(1, 21):
        entry_date = today - timedelta(days=days_ago)
        if entry_date.weekday() >= 5:
            continue

        hours = Decimal(str(rng.choice([6.0, 7.5, 8.0, 8.5])))
        status = rng.choice(statuses)
        approved_by = approver_id if status == TimeEntryStatus.APPROVED else None
        approved_at = datetime.now(
            timezone.utc) if status == TimeEntryStatus.APPROVED else None
        submitted_at = datetime.now(timezone.utc) if status in [
            TimeEntryStatus.SUBMITTED, TimeEntryStatus.APPROVED] else None

        db.add(
            TimeEntry(
                user_id=user_id,
                tenant_id=tenant_id,
                project_id=rng.choice(project_ids),
                entry_date=entry_date,
                hours=hours,
                description="Seeded senior-manager demo activity",
                status=status,
                approved_by=approved_by,
                approved_at=approved_at,
                submitted_at=submitted_at,
            )
        )


async def _ensure_year_time_entries(
    db: AsyncSession,
    *,
    user_id: int,
    project_ids: list[int],
    approver_id: int | None,
    seed: int,
    tenant_id: int,
) -> None:
    today = date.today()
    start_date = today - timedelta(days=364)

    existing_result = await db.execute(
        select(TimeEntry.entry_date)
        .where(TimeEntry.user_id == user_id)
        .where(TimeEntry.entry_date >= start_date)
        .where(TimeEntry.entry_date <= today)
    )
    existing_dates = set(existing_result.scalars().all())

    rng = random.Random(seed)
    statuses = [TimeEntryStatus.DRAFT,
                TimeEntryStatus.SUBMITTED, TimeEntryStatus.APPROVED]

    current_day = start_date
    while current_day <= today:
        if current_day.weekday() < 5 and current_day not in existing_dates:
            hours = Decimal(str(rng.choice([6.0, 7.5, 8.0, 8.5])))
            status = rng.choice(statuses)
            approved_by = approver_id if status == TimeEntryStatus.APPROVED else None
            approved_at = datetime.now(
                timezone.utc) if status == TimeEntryStatus.APPROVED else None
            submitted_at = datetime.now(timezone.utc) if status in [
                TimeEntryStatus.SUBMITTED, TimeEntryStatus.APPROVED] else None

            db.add(
                TimeEntry(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    project_id=rng.choice(project_ids),
                    entry_date=current_day,
                    hours=hours,
                    description="Seeded senior-manager yearly activity",
                    status=status,
                    approved_by=approved_by,
                    approved_at=approved_at,
                    submitted_at=submitted_at,
                )
            )

        current_day += timedelta(days=1)


async def _ensure_demo_rejected_entry(
    db: AsyncSession,
    *,
    user_id: int,
    project_id: int,
    approver_id: int,
    days_ago: int,
    hours: Decimal,
    description: str,
    reason: str,
    tenant_id: int,
) -> None:
    preferred_date = date.today() - timedelta(days=days_ago)
    if preferred_date.weekday() >= 5:
        preferred_date -= timedelta(days=preferred_date.weekday() - 4)

    entry_date = preferred_date
    for offset in range(0, 22):
        candidate = preferred_date + timedelta(days=offset)
        if candidate.weekday() >= 5:
            continue

        daily_total_raw = await db.scalar(
            select(func.coalesce(func.sum(TimeEntry.hours), 0))
            .where(TimeEntry.user_id == user_id)
            .where(TimeEntry.entry_date == candidate)
            .where(TimeEntry.status != TimeEntryStatus.REJECTED)
        )
        daily_total = Decimal(str(daily_total_raw or 0))
        if daily_total + hours <= Decimal("12"):
            entry_date = candidate
            break

    existing_result = await db.execute(
        select(TimeEntry)
        .where(TimeEntry.user_id == user_id)
        .where(TimeEntry.project_id == project_id)
        .where(TimeEntry.status == TimeEntryStatus.REJECTED)
        .where(TimeEntry.hours == hours)
        .where(TimeEntry.rejection_reason == reason)
        .limit(1)
    )
    existing = existing_result.scalars().first()
    if existing is not None:
        existing.entry_date = entry_date
        existing.description = description
        existing.updated_by = approver_id
        db.add(existing)
        return

    now_utc = datetime.now(timezone.utc)
    db.add(
        TimeEntry(
            user_id=user_id,
            tenant_id=tenant_id,
            project_id=project_id,
            entry_date=entry_date,
            hours=hours,
            description=description,
            status=TimeEntryStatus.REJECTED,
            submitted_at=now_utc - timedelta(hours=2),
            approved_by=approver_id,
            approved_at=now_utc,
            rejection_reason=reason,
            created_by=user_id,
            updated_by=approver_id,
        )
    )


async def seed_database() -> None:
    await init_db()

    async with AsyncSessionLocal() as db:
        default_tenant = await _ensure_default_tenant(db)
        await _enable_ingestion_for_demo_tenant(db)
        await db.flush()
        tid = default_tenant.id

        admin = await _ensure_user(
            db,
            email="admin@example.com",
            username="admin",
            full_name="Bharat Mallavarapu",
            title="System Administrator",
            role=UserRole.ADMIN,
            tenant_id=tid,
        )
        ceo = await _ensure_user(
            db,
            email="ceo@example.com",
            username="ceo",
            full_name="Casey CEO",
            title="Chief Executive Officer",
            department="Executive",
            role=UserRole.CEO,
            tenant_id=tid,
        )

        sr_mgr_alex = await _ensure_user(
            db,
            email="alexander@example.com",
            username="alexander",
            full_name="Alexander Chen",
            title="Senior Manager - Engineering",
            department="Engineering",
            role=UserRole.SENIOR_MANAGER,
            tenant_id=tid,
        )
        sr_mgr_margaret = await _ensure_user(
            db,
            email="margaret@example.com",
            username="margaret",
            full_name="Margaret Ross",
            title="Senior Manager - Operations",
            department="Operations",
            role=UserRole.SENIOR_MANAGER,
            tenant_id=tid,
        )

        mgr1 = await _ensure_user(
            db,
            email="manager1@example.com",
            username="manager1",
            full_name="John Doe",
            title="Engineering Manager",
            department="Engineering",
            role=UserRole.MANAGER,
            tenant_id=tid,
        )
        mgr2 = await _ensure_user(
            db,
            email="manager2@example.com",
            username="manager2",
            full_name="Sarah Ops",
            title="Operations Manager",
            department="Operations",
            role=UserRole.MANAGER,
            tenant_id=tid,
        )
        mgr3 = await _ensure_user(
            db,
            email="manager3@example.com",
            username="manager3",
            full_name="Nina Infra",
            title="Infrastructure Manager",
            department="Infrastructure",
            role=UserRole.MANAGER,
            tenant_id=tid,
        )

        emp1 = await _ensure_user(
            db,
            email="emp1-1@example.com",
            username="emp1_1",
            full_name="Yaswanth Mallavarapu",
            title="Senior Software Engineer",
            department="Engineering",
            role=UserRole.EMPLOYEE,
            tenant_id=tid,
        )
        emp2 = await _ensure_user(
            db,
            email="emp1-2@example.com",
            username="emp1_2",
            full_name="Grace Employee",
            title="Senior Software Engineer",
            department="Engineering",
            role=UserRole.EMPLOYEE,
            tenant_id=tid,
        )
        emp3 = await _ensure_user(
            db,
            email="emp1-3@example.com",
            username="emp1_3",
            full_name="Henry Employee",
            title="Software Engineer",
            department="Engineering",
            role=UserRole.EMPLOYEE,
            tenant_id=tid,
        )
        emp4 = await _ensure_user(
            db,
            email="emp3-1@example.com",
            username="emp3_1",
            full_name="Quinn Ops",
            title="Operations Specialist",
            department="Operations",
            role=UserRole.EMPLOYEE,
            tenant_id=tid,
        )
        emp5 = await _ensure_user(
            db,
            email="emp3-2@example.com",
            username="emp3_2",
            full_name="Rachel Ops",
            title="Senior Operations Specialist",
            department="Operations",
            role=UserRole.EMPLOYEE,
            tenant_id=tid,
        )
        emp6 = await _ensure_user(
            db,
            email="emp4-1@example.com",
            username="emp4_1",
            full_name="Victoria Infra",
            title="Infrastructure Engineer",
            department="Infrastructure",
            role=UserRole.EMPLOYEE,
            tenant_id=tid,
        )

        await _ensure_manager_assignment(db, employee_id=sr_mgr_alex.id, manager_id=ceo.id)
        await _ensure_manager_assignment(db, employee_id=sr_mgr_margaret.id, manager_id=ceo.id)

        await _ensure_manager_assignment(db, employee_id=mgr1.id, manager_id=sr_mgr_alex.id)
        await _ensure_manager_assignment(db, employee_id=mgr2.id, manager_id=sr_mgr_margaret.id)
        await _ensure_manager_assignment(db, employee_id=mgr3.id, manager_id=sr_mgr_margaret.id)

        await _ensure_manager_assignment(db, employee_id=emp1.id, manager_id=mgr1.id)
        await _ensure_manager_assignment(db, employee_id=emp2.id, manager_id=mgr1.id)
        await _ensure_manager_assignment(db, employee_id=emp3.id, manager_id=mgr1.id)
        await _ensure_manager_assignment(db, employee_id=emp4.id, manager_id=mgr2.id)
        await _ensure_manager_assignment(db, employee_id=emp5.id, manager_id=mgr2.id)
        await _ensure_manager_assignment(db, employee_id=emp6.id, manager_id=mgr3.id)

        client_tech = await _ensure_client(db, "Tech Innovations Inc", tenant_id=tid)
        client_ops = await _ensure_client(db, "Operations Partners LLC", tenant_id=tid)

        project_ai = await _ensure_project(
            db,
            name="AI Platform Development",
            client_id=client_tech.id,
            billable_rate=Decimal("150.00"),
            code="AI-P",
            description="Engineering delivery and platform improvements",
            tenant_id=tid,
        )
        project_mobile = await _ensure_project(
            db,
            name="Mobile App Modernization",
            client_id=client_tech.id,
            billable_rate=Decimal("135.00"),
            code="MOB",
            description="Mobile modernization workstream",
            tenant_id=tid,
        )
        project_ops = await _ensure_project(
            db,
            name="Operations Enablement",
            client_id=client_ops.id,
            billable_rate=Decimal("125.00"),
            code="OPS",
            description="Operations reporting and process enablement",
            tenant_id=tid,
        )
        project_infra = await _ensure_project(
            db,
            name="Infrastructure Reliability",
            client_id=client_ops.id,
            billable_rate=Decimal("145.00"),
            code="INF",
            description="Infrastructure and reliability initiatives",
            tenant_id=tid,
        )

        await _ensure_project_access(db, user_id=admin.id, project_ids=[project_ai.id, project_mobile.id, project_ops.id, project_infra.id])
        await _ensure_project_access(db, user_id=ceo.id, project_ids=[project_ai.id, project_mobile.id, project_ops.id, project_infra.id])
        await _ensure_project_access(db, user_id=sr_mgr_alex.id, project_ids=[project_ai.id, project_mobile.id])
        await _ensure_project_access(db, user_id=sr_mgr_margaret.id, project_ids=[project_ops.id, project_infra.id])

        await _ensure_project_access(db, user_id=mgr1.id, project_ids=[project_ai.id, project_mobile.id])
        await _ensure_project_access(db, user_id=mgr2.id, project_ids=[project_ops.id])
        await _ensure_project_access(db, user_id=mgr3.id, project_ids=[project_infra.id])

        await _ensure_project_access(db, user_id=emp1.id, project_ids=[project_ai.id])
        await _ensure_project_access(db, user_id=emp2.id, project_ids=[project_mobile.id])
        await _ensure_project_access(db, user_id=emp3.id, project_ids=[project_ai.id, project_mobile.id])
        await _ensure_project_access(db, user_id=emp4.id, project_ids=[project_ops.id])
        await _ensure_project_access(db, user_id=emp5.id, project_ids=[project_ops.id])
        await _ensure_project_access(db, user_id=emp6.id, project_ids=[project_infra.id])

        await _ensure_recent_time_entries(
            db,
            user_id=sr_mgr_alex.id,
            project_ids=[project_ai.id, project_mobile.id],
            approver_id=ceo.id,
            seed=101,
            tenant_id=tid,
        )
        await _ensure_year_time_entries(
            db,
            user_id=sr_mgr_alex.id,
            project_ids=[project_ai.id, project_mobile.id],
            approver_id=ceo.id,
            seed=1001,
            tenant_id=tid,
        )
        await _ensure_recent_time_entries(
            db,
            user_id=sr_mgr_margaret.id,
            project_ids=[project_ops.id, project_infra.id],
            approver_id=ceo.id,
            seed=102,
            tenant_id=tid,
        )
        await _ensure_year_time_entries(
            db,
            user_id=sr_mgr_margaret.id,
            project_ids=[project_ops.id, project_infra.id],
            approver_id=ceo.id,
            seed=1002,
            tenant_id=tid,
        )
        await _ensure_recent_time_entries(
            db,
            user_id=mgr1.id,
            project_ids=[project_ai.id, project_mobile.id],
            approver_id=sr_mgr_alex.id,
            seed=103,
            tenant_id=tid,
        )
        await _ensure_recent_time_entries(
            db,
            user_id=mgr2.id,
            project_ids=[project_ops.id],
            approver_id=sr_mgr_margaret.id,
            seed=104,
            tenant_id=tid,
        )
        await _ensure_recent_time_entries(
            db,
            user_id=mgr3.id,
            project_ids=[project_infra.id],
            approver_id=sr_mgr_margaret.id,
            seed=105,
            tenant_id=tid,
        )

        await _ensure_recent_time_entries(
            db,
            user_id=emp1.id,
            project_ids=[project_ai.id],
            approver_id=mgr1.id,
            seed=201,
            tenant_id=tid,
        )
        await _ensure_recent_time_entries(
            db,
            user_id=emp2.id,
            project_ids=[project_mobile.id],
            approver_id=mgr1.id,
            seed=202,
            tenant_id=tid,
        )
        await _ensure_recent_time_entries(
            db,
            user_id=emp3.id,
            project_ids=[project_ai.id, project_mobile.id],
            approver_id=mgr1.id,
            seed=203,
            tenant_id=tid,
        )
        await _ensure_recent_time_entries(
            db,
            user_id=emp4.id,
            project_ids=[project_ops.id],
            approver_id=mgr2.id,
            seed=204,
            tenant_id=tid,
        )
        await _ensure_recent_time_entries(
            db,
            user_id=emp5.id,
            project_ids=[project_ops.id],
            approver_id=mgr2.id,
            seed=205,
            tenant_id=tid,
        )
        await _ensure_recent_time_entries(
            db,
            user_id=emp6.id,
            project_ids=[project_infra.id],
            approver_id=mgr3.id,
            seed=206,
            tenant_id=tid,
        )

        await _ensure_demo_rejected_entry(
            db,
            user_id=emp1.id,
            project_id=project_ai.id,
            approver_id=mgr1.id,
            days_ago=2,
            hours=Decimal("7.5"),
            description="Implemented model-serving API endpoints and updated integration notes.",
            reason="Please split design and implementation notes before resubmitting.",
            tenant_id=tid,
        )
        await _ensure_demo_rejected_entry(
            db,
            user_id=emp2.id,
            project_id=project_mobile.id,
            approver_id=mgr1.id,
            days_ago=3,
            hours=Decimal("8.0"),
            description="Refactored authentication flow for iOS and Android sign-in screens.",
            reason="Need clearer task-level detail for approval.",
            tenant_id=tid,
        )
        await _ensure_demo_rejected_entry(
            db,
            user_id=emp4.id,
            project_id=project_ops.id,
            approver_id=mgr2.id,
            days_ago=4,
            hours=Decimal("6.5"),
            description="Built operations dashboard export and validated weekly metric totals.",
            reason="Please attach process context in the description.",
            tenant_id=tid,
        )
        await _ensure_demo_rejected_entry(
            db,
            user_id=emp6.id,
            project_id=project_infra.id,
            approver_id=mgr3.id,
            days_ago=5,
            hours=Decimal("7.0"),
            description="Investigated service latency spikes and applied reliability tuning changes.",
            reason="Provide incident reference and impact notes.",
            tenant_id=tid,
        )

        await db.commit()

    # Provision system service users for ALL tenants (idempotent)
    async with AsyncSessionLocal() as db:
        all_tenants_result = await db.execute(select(Tenant))
        for tenant in all_tenants_result.scalars().all():
            await _ensure_system_service_user(db, tenant_id=tenant.id)

    print("[OK] Seed complete (idempotent): senior managers now have direct reports, projects, and activity data")
    print("   Quick login:")
    print("   - Sr. Manager (Margaret): margaret@example.com / password")
    print("   - Sr. Manager (Alexander): alexander@example.com / password")


if __name__ == "__main__":
    asyncio.run(seed_database())
