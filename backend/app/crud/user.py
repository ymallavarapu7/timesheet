from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from app.models.user import User, UserRole
from app.models.project import Project
from app.models.time_entry import TimeEntry
from app.models.time_off_request import TimeOffRequest
from app.models.assignments import EmployeeManagerAssignment, UserProjectAccess
from app.schemas import UserCreate, UserUpdate
from app.core.security import get_password_hash
from typing import Optional
import secrets
import string


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    """Get user by ID."""
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.manager_assignment),
            selectinload(User.project_access),
        )
    )
    return result.scalars().first()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Get user by email."""
    normalized_email = email.strip().lower()
    result = await db.execute(
        select(User)
        .where(User.email == normalized_email)
        .options(
            selectinload(User.manager_assignment),
            selectinload(User.project_access),
        )
    )
    return result.scalars().first()


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    """Get user by username."""
    normalized_username = username.strip().lower()
    result = await db.execute(
        select(User).where(User.username == normalized_username)
    )
    return result.scalars().first()


async def _sync_user_assignments(
    db: AsyncSession,
    user: User,
    role: UserRole,
    manager_id: Optional[int],
    project_ids: list[int],
) -> None:
    await db.execute(delete(UserProjectAccess).where(UserProjectAccess.user_id == user.id))
    await db.execute(delete(EmployeeManagerAssignment).where(EmployeeManagerAssignment.employee_id == user.id))

    if manager_id is not None:
        if manager_id == user.id:
            raise ValueError("A user cannot be their own manager")

        manager = await get_user_by_id(db, manager_id)
        allowed_manager_roles = _allowed_manager_roles_for_role(role)
        if not allowed_manager_roles:
            raise ValueError("Selected role cannot have a supervisor")

        if not manager or manager.role not in allowed_manager_roles:
            raise ValueError("Selected supervisor is invalid")

        # Validate that the manager belongs to the same tenant
        if user.tenant_id is not None and manager.tenant_id != user.tenant_id:
            raise ValueError("Selected supervisor must belong to the same tenant")

        db.add(EmployeeManagerAssignment(
            employee_id=user.id, manager_id=manager_id))

    unique_project_ids = sorted(set(project_ids or []))
    if not unique_project_ids:
        return

    # Validate that all projects belong to the same tenant as the user
    query = select(Project.id).where(Project.id.in_(unique_project_ids))
    if user.tenant_id is not None:
        query = query.where(Project.tenant_id == user.tenant_id)
    result = await db.execute(query)
    valid_project_ids = {project_id for project_id in result.scalars().all()}
    missing_ids = [
        project_id for project_id in unique_project_ids if project_id not in valid_project_ids]
    if missing_ids:
        raise ValueError("One or more selected projects are invalid or belong to a different tenant")

    db.add_all(
        [UserProjectAccess(user_id=user.id, project_id=project_id)
         for project_id in unique_project_ids]
    )


def _normalize_profile_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _validate_role_profile(role: UserRole, title: Optional[str], department: Optional[str]) -> None:
    if role == UserRole.MANAGER:
        if not title:
            raise ValueError("Manager title is required")
        if not department:
            raise ValueError("Manager department is required")
    elif role == UserRole.EMPLOYEE:
        if not title:
            raise ValueError("Employee title is required")


def _allowed_manager_roles_for_role(role: UserRole) -> set[UserRole]:
    if role == UserRole.EMPLOYEE:
        return {UserRole.MANAGER, UserRole.SENIOR_MANAGER, UserRole.CEO, UserRole.ADMIN}
    if role == UserRole.MANAGER:
        return {UserRole.SENIOR_MANAGER, UserRole.CEO}
    if role == UserRole.SENIOR_MANAGER:
        return {UserRole.CEO}
    if role == UserRole.ADMIN:
        # Admins are employees with elevated permissions; their reporting chain
        # follows normal org lines — any people-manager role, including another
        # admin, is a valid supervisor.
        return {UserRole.MANAGER, UserRole.SENIOR_MANAGER, UserRole.CEO, UserRole.ADMIN}
    return set()


def _generate_default_password() -> str:
    """Generate a secure default password for new users (meets password policy)."""
    # Guarantee at least one of each required character type
    required = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*"),
    ]
    # Fill remaining length with random chars
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    remaining = [secrets.choice(chars) for _ in range(12)]
    combined = required + remaining
    # Shuffle to avoid predictable positions
    result = list(combined)
    import random
    random.SystemRandom().shuffle(result)
    return ''.join(result)


async def create_user(db: AsyncSession, user_create: UserCreate) -> tuple["User", str]:
    """Create a new user. Returns (user, plaintext_password) so callers can relay the temp password."""
    role = user_create.role or UserRole.EMPLOYEE
    normalized_title = _normalize_profile_text(user_create.title)
    normalized_department = _normalize_profile_text(user_create.department)
    _validate_role_profile(role, normalized_title, normalized_department)

    # Always generate a secure random temporary password; ignore any client-supplied value.
    password = _generate_default_password()

    db_user = User(
        tenant_id=user_create.tenant_id,
        email=user_create.email.strip().lower(),
        username=user_create.username.strip().lower(),
        full_name=user_create.full_name.strip(),
        title=normalized_title,
        department=normalized_department,
        hashed_password=get_password_hash(password),
        has_changed_password=False,
        email_verified=False,
        role=role,
        is_active=user_create.is_active,
        can_review=user_create.can_review,
        is_external=user_create.is_external,
        default_client_id=user_create.default_client_id,
    )
    db.add(db_user)
    try:
        await db.flush()
        await _sync_user_assignments(
            db,
            db_user,
            role,
            user_create.manager_id,
            user_create.project_ids,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    except ValueError:
        await db.rollback()
        raise
    user = await get_user_by_id(db, db_user.id)
    return user, password


async def update_user(db: AsyncSession, user: User, user_update: UserUpdate) -> User:
    """Update user fields."""
    update_data = user_update.model_dump(exclude_unset=True)

    manager_id_supplied = "manager_id" in update_data
    project_ids_supplied = "project_ids" in update_data
    manager_id = update_data.pop("manager_id", user.manager_id)
    project_ids = update_data.pop("project_ids", user.project_ids)

    if "email" in update_data and update_data["email"] is not None:
        update_data["email"] = update_data["email"].strip().lower()

    if "username" in update_data and update_data["username"] is not None:
        update_data["username"] = update_data["username"].strip().lower()

    if "full_name" in update_data and update_data["full_name"] is not None:
        update_data["full_name"] = update_data["full_name"].strip()

    if "title" in update_data:
        update_data["title"] = _normalize_profile_text(update_data["title"])

    if "department" in update_data:
        update_data["department"] = _normalize_profile_text(
            update_data["department"])

    if "password" in update_data:
        update_data["hashed_password"] = get_password_hash(
            update_data.pop("password"))

    next_role = update_data.get("role", user.role)
    next_title = update_data.get("title", user.title)
    next_department = update_data.get("department", user.department)
    _validate_role_profile(next_role, next_title, next_department)

    if "default_client_id" in update_data and update_data["default_client_id"] is not None:
        from app.models.client import Client
        client_result = await db.execute(
            select(Client).where(Client.id == update_data["default_client_id"])
        )
        client_row = client_result.scalar_one_or_none()
        if client_row is None or (user.tenant_id is not None and client_row.tenant_id != user.tenant_id):
            raise ValueError("default_client_id references a client from a different tenant or it doesn't exist")

    if not manager_id_supplied:
        manager_id = user.manager_id
    if not project_ids_supplied:
        project_ids = user.project_ids

    for field, value in update_data.items():
        setattr(user, field, value)

    db.add(user)
    try:
        await db.flush()
        await _sync_user_assignments(db, user, next_role, manager_id, project_ids or [])
        await db.commit()
    except ValueError:
        await db.rollback()
        raise
    return await get_user_by_id(db, user.id)


async def delete_user(db: AsyncSession, user_id: int) -> bool:
    """Delete user by ID, including dependent records/references."""
    user = await get_user_by_id(db, user_id)
    if user:
        try:
            await db.execute(delete(UserProjectAccess).where(UserProjectAccess.user_id == user_id))
            await db.execute(
                delete(EmployeeManagerAssignment).where(
                    (EmployeeManagerAssignment.employee_id == user_id)
                    | (EmployeeManagerAssignment.manager_id == user_id)
                )
            )
            # Keep historical approval records valid by clearing approver references.
            await db.execute(
                update(TimeEntry)
                .where(TimeEntry.approved_by == user_id)
                .values(approved_by=None)
            )
            await db.execute(
                update(TimeOffRequest)
                .where(TimeOffRequest.approved_by == user_id)
                .values(approved_by=None)
            )
            # Clear created_by and updated_by audit references
            await db.execute(
                update(TimeEntry)
                .where(TimeEntry.created_by == user_id)
                .values(created_by=None)
            )
            await db.execute(
                update(TimeEntry)
                .where(TimeEntry.updated_by == user_id)
                .values(updated_by=None)
            )
            await db.execute(
                update(TimeOffRequest)
                .where(TimeOffRequest.created_by == user_id)
                .values(created_by=None)
            )
            await db.execute(
                update(TimeOffRequest)
                .where(TimeOffRequest.updated_by == user_id)
                .values(updated_by=None)
            )

            # Remove the user's owned records so seeded/demo users can be deleted cleanly.
            await db.execute(delete(TimeEntry).where(TimeEntry.user_id == user_id))
            await db.execute(delete(TimeOffRequest).where(TimeOffRequest.user_id == user_id))

            # Clear ingestion references (user might be auto-created by ingestion).
            # These tables may or may not have CASCADE/SET NULL constraints depending
            # on whether DB migrations were applied, so clear them explicitly.
            from app.models.ingestion_timesheet import IngestionTimesheet
            from app.models.activity_log import ActivityLog

            await db.execute(
                update(IngestionTimesheet)
                .where(IngestionTimesheet.employee_id == user_id)
                .values(employee_id=None)
            )
            await db.execute(
                update(IngestionTimesheet)
                .where(IngestionTimesheet.reviewer_id == user_id)
                .values(reviewer_id=None)
            )
            await db.execute(
                update(ActivityLog)
                .where(ActivityLog.actor_user_id == user_id)
                .values(actor_user_id=None)
            )

            # Clear time_entry_edit_history edited_by references
            from sqlalchemy import text as sa_text
            await db.execute(
                sa_text("UPDATE time_entry_edit_history SET edited_by = NULL WHERE edited_by = :uid"),
                {"uid": user_id},
            )
            # Clear ingestion_audit_log user_id references
            await db.execute(
                sa_text("UPDATE ingestion_audit_log SET user_id = NULL WHERE user_id = :uid"),
                {"uid": user_id},
            )

            await db.delete(user)
            await db.commit()
            return True
        except IntegrityError:
            await db.rollback()
            raise
    return False


async def list_users(db: AsyncSession, tenant_id: int, skip: int = 0, limit: int = 100) -> list[User]:
    """List all users for a tenant with pagination."""
    result = await db.execute(
        select(User)
        .where(User.tenant_id == tenant_id)
        .options(
            selectinload(User.manager_assignment),
            selectinload(User.project_access),
        )
        .order_by(User.full_name.asc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def list_users_by_role(db: AsyncSession, role: UserRole, tenant_id: int, skip: int = 0, limit: int = 100) -> list[User]:
    """List users by role within a tenant."""
    result = await db.execute(
        select(User)
        .where(User.role == role, User.tenant_id == tenant_id)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()
