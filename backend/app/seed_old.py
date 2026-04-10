"""
Seed script to populate the database with sample data.
Run with: python -m app.seed
"""
import asyncio
import random
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings
from app.models.base import Base
from app.models.user import User, UserRole
from app.models.assignments import EmployeeManagerAssignment
from app.models.client import Client
from app.models.project import Project
from app.models.time_entry import TimeEntry, TimeEntryStatus
from app.models.time_off_request import TimeOffRequest, TimeOffStatus, TimeOffType
from app.core.security import get_password_hash


def move_to_previous_weekday(value: date) -> date:
    """Shift weekend dates back to the previous Friday for seed/demo data."""
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def move_to_next_weekday(value: date) -> date:
    """Shift weekend dates forward to the next Monday."""
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def previous_working_day(reference: date) -> date:
    """Return the latest working day before the provided date."""
    candidate = reference - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


async def seed_database():
    """Seed the database with sample data."""

    # Create engine and session
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        rng = random.Random(20260314)

        # Create users
        admin1 = User(
            email="admin@example.com",
            full_name="Bharat Mallavarapu",
            title="System Administrator",
            hashed_password=get_password_hash("password"),
            role=UserRole.ADMIN,
            is_active=True,
        )
        admin2 = User(
            email="admin2@example.com",
            full_name="Bob Admin",
            hashed_password=get_password_hash("password"),
            role=UserRole.ADMIN,
            is_active=True,
        )

        manager1 = User(
            email="manager@example.com",
            full_name="John Doe",
            title="Manager",
            department="Software Engineering",
            hashed_password=get_password_hash("password"),
            role=UserRole.MANAGER,
            is_active=True,
        )
        manager2 = User(
            email="manager2@example.com",
            full_name="Alex Senior Manager",
            title="Senior Manager",
            department="Engineering Leadership",
            hashed_password=get_password_hash("password"),
            role=UserRole.MANAGER,
            is_active=True,
        )
        manager3 = User(
            email="manager3@example.com",
            full_name="Eve Manager",
            title="Manager",
            department="Operations",
            hashed_password=get_password_hash("password"),
            role=UserRole.MANAGER,
            is_active=True,
        )

        emp1 = User(
            email="emp1@example.com",
            full_name="Yaswanth Mallavarapu",
            title="Associate Engineer",
            department="Software Engineering",
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=True,
        )
        emp2 = User(
            email="emp2@example.com",
            full_name="Grace Employee",
            title="Senior Software Engineer",
            department="Software Engineering",
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=True,
        )
        emp3 = User(
            email="emp3@example.com",
            full_name="Henry Employee",
            title="Associate Engineer",
            department="Software Engineering",
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=True,
        )
        emp4 = User(
            email="emp4@example.com",
            full_name="Ivy Employee",
            title="Senior Software Engineer",
            department="Software Engineering",
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=True,
        )
        emp5 = User(
            email="emp5@example.com",
            full_name="Jack Employee",
            title="Associate Engineer",
            department="Infrastructure",
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=True,
        )
        emp6 = User(
            email="emp6@example.com",
            full_name="Kelly Employee",
            title="Senior Software Engineer",
            department="Infrastructure",
            hashed_password=get_password_hash("password"),
            role=UserRole.EMPLOYEE,
            is_active=True,
        )

        session.add_all([admin1, admin2, manager1, manager2,
                        manager3, emp1, emp2, emp3, emp4, emp5, emp6])
        await session.flush()

        admin2.email = "ceo@example.com"
        admin2.full_name = "Casey CEO"
        admin2.title = "CEO"

        session.add_all([
            EmployeeManagerAssignment(
                employee_id=admin1.id, manager_id=manager1.id),
            EmployeeManagerAssignment(
                employee_id=manager1.id, manager_id=manager2.id),
            EmployeeManagerAssignment(
                employee_id=manager2.id, manager_id=admin2.id),
            EmployeeManagerAssignment(
                employee_id=manager3.id, manager_id=manager2.id),
            EmployeeManagerAssignment(
                employee_id=emp1.id, manager_id=manager1.id),
            EmployeeManagerAssignment(
                employee_id=emp2.id, manager_id=manager1.id),
            EmployeeManagerAssignment(
                employee_id=emp3.id, manager_id=manager1.id),
            EmployeeManagerAssignment(
                employee_id=emp4.id, manager_id=manager1.id),
            EmployeeManagerAssignment(
                employee_id=emp5.id, manager_id=manager1.id),
            EmployeeManagerAssignment(
                employee_id=emp6.id, manager_id=manager1.id),
        ])

        # Create clients
        client1 = Client(name="Acme Corp", quickbooks_customer_id=None)
        client2 = Client(name="TechStart Inc", quickbooks_customer_id=None)
        client3 = Client(name="Global Industries", quickbooks_customer_id=None)

        session.add_all([client1, client2, client3])
        await session.flush()

        # Create projects
        proj1 = Project(
            name="Website Redesign",
            client_id=client1.id,
            billable_rate=Decimal("150.00"),
            is_active=True,
        )
        proj2 = Project(
            name="API Development",
            client_id=client1.id,
            billable_rate=Decimal("175.00"),
            is_active=True,
        )
        proj3 = Project(
            name="Mobile App",
            client_id=client2.id,
            billable_rate=Decimal("200.00"),
            is_active=True,
        )
        proj4 = Project(
            name="Infrastructure Setup",
            client_id=client3.id,
            billable_rate=Decimal("160.00"),
            is_active=True,
        )

        session.add_all([proj1, proj2, proj3, proj4])
        await session.flush()

        # Create one year of weekday time entries
        today = move_to_previous_weekday(date.today())
        start_date = today - timedelta(days=364)
        weekday_dates = [
            day for day in (
                start_date + timedelta(days=offset)
                for offset in range((today - start_date).days + 1)
            )
            if day.weekday() < 5
        ]
        snapshot_target_date = previous_working_day(date.today())

        employees = [emp1, emp2, emp3, emp4, emp5, emp6]
        employee_project_mix = {
            emp1.id: [proj1.id, proj2.id],
            emp2.id: [proj1.id, proj3.id],
            emp3.id: [proj2.id, proj1.id],
            emp4.id: [proj3.id, proj2.id],
            emp5.id: [proj4.id, proj2.id],
            emp6.id: [proj4.id, proj3.id],
        }
        manager_cycle = [manager1.id]
        descriptions_by_project = {
            proj1.id: [
                "Frontend component implementation",
                "Responsive UI polish",
                "Accessibility fixes",
                "Design review updates",
                "Client feedback changes",
            ],
            proj2.id: [
                "API endpoint implementation",
                "Schema and contract updates",
                "Backend integration testing",
                "Auth and permission improvements",
                "Performance optimization",
            ],
            proj3.id: [
                "Mobile feature development",
                "Navigation flow improvements",
                "Crash fix and stability pass",
                "Device compatibility checks",
                "App UI refinement",
            ],
            proj4.id: [
                "Infrastructure automation",
                "Deployment configuration updates",
                "Monitoring and alerting setup",
                "Environment hardening",
                "Operational maintenance tasks",
            ],
        }
        rejection_reasons = [
            "Please add more implementation details before resubmitting",
            "Hours look high for this task; clarify work split",
            "Description is too brief; include outcome and scope",
            "Entry needs clearer mapping to project deliverables",
        ]

        def random_hours() -> Decimal:
            # Quarter-hour increments from 5.5h to 9.5h, centered near 8h.
            quarter_steps = rng.choices(
                population=list(range(22, 39)),
                weights=[1, 1, 2, 2, 3, 4, 6, 8, 9, 10, 9, 8, 7, 6, 4, 3, 2],
                k=1,
            )[0]
            return Decimal(str(quarter_steps / 4))

        generated_time_entries = 0
        for emp_index, employee in enumerate(employees):
            manager_id = manager_cycle[emp_index % len(manager_cycle)]
            primary_project_id, secondary_project_id = employee_project_mix[employee.id]

            for day_index, entry_date in enumerate(weekday_dates):
                days_ago = (today - entry_date).days

                if entry_date == snapshot_target_date:
                    if emp_index in {0, 2, 5}:
                        forced_status = TimeEntryStatus.SUBMITTED
                    elif emp_index in {1, 3}:
                        forced_status = TimeEntryStatus.DRAFT
                    else:
                        forced_status = None

                    if forced_status is None:
                        continue
                else:
                    forced_status = None

                # Skip a small percentage of older weekdays to avoid fixed weekly totals.
                if days_ago > 10 and rng.random() < 0.08:
                    continue

                project_id = secondary_project_id if rng.random() < 0.22 else primary_project_id
                description = rng.choice(descriptions_by_project[project_id])
                hours = random_hours()

                if entry_date.weekday() == 4 and rng.random() < 0.35:
                    hours = max(Decimal("5.5"), hours - Decimal("0.5"))
                if rng.random() < 0.06:
                    hours = max(Decimal("4.0"), hours - Decimal("1.5"))

                status = TimeEntryStatus.APPROVED
                submitted_at = None
                approved_at = None
                approved_by = None
                rejection_reason = None

                if forced_status is not None:
                    status = forced_status
                    if status == TimeEntryStatus.SUBMITTED:
                        submitted_at = today
                elif days_ago <= 1:
                    status = TimeEntryStatus.DRAFT
                elif days_ago <= 4:
                    status = TimeEntryStatus.SUBMITTED
                    submitted_at = move_to_next_weekday(
                        entry_date + timedelta(days=1))
                    if submitted_at > today:
                        submitted_at = today
                elif days_ago <= 7:
                    status = TimeEntryStatus.DRAFT if rng.random() < 0.35 else TimeEntryStatus.SUBMITTED
                    if status == TimeEntryStatus.SUBMITTED:
                        submitted_at = move_to_next_weekday(
                            entry_date + timedelta(days=1))
                        if submitted_at > today:
                            submitted_at = today
                elif rng.random() < 0.09:
                    status = TimeEntryStatus.REJECTED
                    submitted_at = move_to_next_weekday(
                        entry_date + timedelta(days=1))
                    approved_at = move_to_next_weekday(
                        entry_date + timedelta(days=2))
                    if approved_at > today:
                        approved_at = today
                    approved_by = manager_id
                    rejection_reason = rng.choice(rejection_reasons)
                elif rng.random() < 0.04:
                    status = TimeEntryStatus.SUBMITTED
                    submitted_at = move_to_next_weekday(
                        entry_date + timedelta(days=1))
                    if submitted_at > today:
                        submitted_at = today
                else:
                    status = TimeEntryStatus.APPROVED
                    submitted_at = move_to_next_weekday(
                        entry_date + timedelta(days=1))
                    approved_at = move_to_next_weekday(
                        entry_date + timedelta(days=2))
                    if approved_at > today:
                        approved_at = today
                    approved_by = manager_id

                entry = TimeEntry(
                    user_id=employee.id,
                    project_id=project_id,
                    entry_date=entry_date,
                    hours=hours,
                    description=description,
                    status=status,
                    submitted_at=submitted_at,
                    approved_by=approved_by,
                    approved_at=approved_at,
                    rejection_reason=rejection_reason,
                )
                session.add(entry)
                generated_time_entries += 1

        # Dedicated time off requests
        time_off_items = [
            TimeOffRequest(
                user_id=emp1.id,
                request_date=today + timedelta(days=2),
                hours=Decimal("8.0"),
                leave_type=TimeOffType.PTO,
                reason="Family function",
                status=TimeOffStatus.DRAFT,
            ),
            TimeOffRequest(
                user_id=emp2.id,
                request_date=today - timedelta(days=1),
                hours=Decimal("4.0"),
                leave_type=TimeOffType.HALF_DAY,
                reason="Medical appointment",
                status=TimeOffStatus.SUBMITTED,
                submitted_at=today,
            ),
            TimeOffRequest(
                user_id=emp3.id,
                request_date=today - timedelta(days=6),
                hours=Decimal("8.0"),
                leave_type=TimeOffType.SICK_DAY,
                reason="Flu recovery",
                status=TimeOffStatus.APPROVED,
                submitted_at=today - timedelta(days=5),
                approved_by=manager1.id,
                approved_at=today - timedelta(days=4),
            ),
            TimeOffRequest(
                user_id=emp4.id,
                request_date=today - timedelta(days=3),
                hours=Decimal("2.0"),
                leave_type=TimeOffType.HOURLY_PERMISSION,
                reason="Bank visit",
                status=TimeOffStatus.REJECTED,
                submitted_at=today - timedelta(days=2),
                approved_by=manager2.id,
                approved_at=today - timedelta(days=1),
                rejection_reason="Please request in advance",
            ),
        ]
        session.add_all(time_off_items)

        await session.commit()
        print("âœ“ Database seeded successfully!")
        print("\nðŸ“Š Sample Data Summary:")
        print(f"  â€¢ Admins: 2 (bharat admin, casey ceo) - password: password")
        print(f"  â€¢ Managers: 3 (john, alex senior manager, eve) - password: password")
        print(f"  â€¢ Employees: 6 (yaswanth, grace, henry, ivy, jack, kelly) - password: password")
        print("  â€¢ Reporting: admin@example.com + employees -> manager@example.com -> manager2@example.com -> ceo@example.com")
        print("  â€¢ Latest working day mix: 3 submitted, 2 draft, 1 no-entry (manager snapshot realism)")
        print(f"  â€¢ Clients: 3 (Acme, TechStart, Global)")
        print(f"  â€¢ Projects: 4 (across the clients)")
        print(
            f"  â€¢ Time Entries: {generated_time_entries} weekday entries across ~1 year with mixed statuses\n")
        print(f"  â€¢ Time Off Requests: Mixed statuses (DRAFT, SUBMITTED, APPROVED, REJECTED)\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_database())

