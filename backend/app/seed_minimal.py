"""Minimal seed file for testing - used when main seed.py is corrupted."""
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.core.config import settings
from app.models.base import Base
from app.models.user import User, UserRole
from app.core.security import get_password_hash


async def seed_database():
    """Seed the database with minimal sample data for testing."""
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Check if database already has data
    async with AsyncSessionLocal() as session:
        existing_users = await session.execute(select(User).limit(1))
        if existing_users.scalar_one_or_none():
            print("[OK] Database already seeded.")
            await engine.dispose()
            return

    # Create minimal test users
    async with AsyncSessionLocal() as session:
        test_users = [
            User(
                email="admin@example.com",
                username="admin",
                full_name="Bharat Mallavarapu",
                title="Administrator",
                department="Administration",
                hashed_password=get_password_hash("password"),
                has_changed_password=True,
                role=UserRole.ADMIN,
                is_active=True
            ),
            User(
                email="ceo@example.com",
                username="ceo",
                full_name="Casey CEO",
                department="Executive",
                hashed_password=get_password_hash("password"),
                has_changed_password=True,
                role=UserRole.CEO,
                is_active=True
            ),
            User(
                email="manager@example.com",
                username="manager",
                full_name="John Manager",
                title="Engineering Manager",
                department="Engineering",
                hashed_password=get_password_hash("password"),
                has_changed_password=True,
                role=UserRole.MANAGER,
                is_active=True
            ),
            User(
                email="emp1@example.com",
                username="emp1",
                full_name="Employee One",
                title="Senior Engineer",
                department="Engineering",
                hashed_password=get_password_hash("password"),
                has_changed_password=True,
                role=UserRole.EMPLOYEE,
                is_active=True
            ),
        ]

        for user in test_users:
            session.add(user)

        await session.commit()

    await engine.dispose()
    print("[OK] Minimal test database created")

if __name__ == "__main__":
    asyncio.run(seed_database())
