from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import inspect, text
from app.core.config import settings
from app.models.base import Base
from app import models  # noqa: F401

# Create async engine
_is_sqlite = "sqlite" in settings.database_url
engine = create_async_engine(
    settings.database_url,
    echo=False,  # SQL logging disabled — enable with echo="debug" for troubleshooting
    future=True,
    pool_pre_ping=True,  # Verify connection is alive before using
    **({} if _is_sqlite else {
        "pool_size": 10,
        "max_overflow": 5,
    }),
)

# Create session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db():
    """Dependency injection for database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Initialize database (create tables)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_backfill_legacy_schema)

    # Apply additive migrations for older local databases after base tables exist.
    from app.migrate import migrate

    await migrate()


def _backfill_legacy_schema(sync_conn):
    """Backfill missing columns/indexes for legacy databases."""
    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    if "users" not in tables:
        return

    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    dialect = sync_conn.dialect.name

    if "username" not in existing_columns:
        sync_conn.execute(
            text("ALTER TABLE users ADD COLUMN username VARCHAR(255)"))

        if dialect == "postgresql":
            sync_conn.execute(
                text(
                    "UPDATE users SET username = split_part(email, '@', 1) WHERE username IS NULL")
            )
            sync_conn.execute(
                text("ALTER TABLE users ALTER COLUMN username SET NOT NULL"))
            sync_conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"))
        elif dialect == "sqlite":
            sync_conn.execute(
                text(
                    "UPDATE users SET username = substr(email, 1, instr(email, '@') - 1) WHERE username IS NULL")
            )

    if "has_changed_password" not in existing_columns:
        if dialect == "postgresql":
            sync_conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN has_changed_password BOOLEAN NOT NULL DEFAULT FALSE")
            )
        else:
            sync_conn.execute(
                text("ALTER TABLE users ADD COLUMN has_changed_password BOOLEAN DEFAULT 0")
            )
            sync_conn.execute(
                text(
                    "UPDATE users SET has_changed_password = 0 WHERE has_changed_password IS NULL")
            )


async def close_db():
    """Close database connection."""
    await engine.dispose()
